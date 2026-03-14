import hashlib
import logging
from pathlib import Path
from uuid import UUID
from typing import Optional, Any


from tree_sitter import Language as TSLanguage, Parser, Query

try:
    from tree_sitter import QueryCursor
except ImportError:
    QueryCursor = None

import tree_sitter_kotlin
from .base import LanguageParser
from ...domain.models import CodeSymbol, APIExport

logger = logging.getLogger(__name__)


class KotlinParser(LanguageParser):
    """
    Parser implementation for Kotlin source files.
    Focuses on AST-based symbol extraction and cross-language dependency mapping
    within standard Android project structures.
    """
    def __init__(self):
        super().__init__()
        self.language = TSLanguage(tree_sitter_kotlin.language())
        self.parser = Parser(self.language)

    def _get_file_extensions(self) -> set[str]:
        return {".kt"}

    def _get_init_files(self) -> set[str]:
        return set()

    def extract_dependencies(self, file_path: Path, repo_path: Path) -> list[str]:
        """
        Orchestrates the dependency extraction by mapping import statements
        to physical files within the repository.
        """
        resolved_paths = []
        try:
            content = file_path.read_bytes()
            tree = self.parser.parse(content)
            raw_imports = self._extract_raw_imports(tree.root_node)

            for imp in raw_imports:
                resolved = self._resolve_import_path(imp, file_path, repo_path)
                resolved_paths.extend(resolved)
        except:
            pass
        return list(set(resolved_paths))

    def _resolve_import_path(self, import_name: str, file_path: Path, repo_path: Path) -> list[str]:
        """
        Resolves Kotlin/Java package imports to physical file paths.
        Specially tuned for Android projects to handle:
        1. Wildcard imports (.*)
        2. Mixed Kotlin/Java source sets
        3. Standard Android source roots (app/src/main/...)
        """
        resolved = []
        is_wildcard = import_name.endswith('.*')

        clean_import = import_name.replace('.*', '')
        base_path_str = clean_import.replace('.', '/')

        possible_roots = [
            "app/src/main/java",
            "app/src/main/kotlin",
            "src/main/java",
            "src/main/kotlin"
        ]

        for root in possible_roots:
            full_root_path = repo_path / root
            candidate_base = full_root_path / base_path_str

            if not is_wildcard:
                for ext in [".kt", ".java"]:
                    candidate_file = candidate_base.with_suffix(ext)
                    if candidate_file.exists():
                        resolved.append(str(candidate_file.relative_to(repo_path)))
                        return resolved

            else:
                if candidate_base.exists() and candidate_base.is_dir():
                    for p in candidate_base.glob("*"):
                        if p.suffix in [".kt", ".java"]:
                            resolved.append(str(p.relative_to(repo_path)))
                    if resolved:
                        return resolved

        return resolved

    def _extract_raw_imports(self, root_node) -> list[str]:
        """
        Parses the AST to extract raw import text,
        cleaning up keywords and semicolons.
        """
        raw_imports = []
        for child in root_node.children:
            if 'import' in child.type.lower():
                text = child.text.decode('utf-8').replace('import', '').replace(';', '').strip()
                if text:
                    raw_imports.append(text)
        return list(set(raw_imports))

    def extract_code_structure(self, file_path: Path, repo_path: Path) -> tuple:
        """
        Recursive AST traversal to identify class, function, and object declarations.
        Generates stable UUIDs via SHA256 based on file path and line context.
        """
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            tree = self.parser.parse(content.encode('utf-8'))

            symbols = self._extract_symbols(tree.root_node, file_path, content)

            exports = [
                APIExport(
                    name=s.name,
                    export_type=s.symbol_type,
                    symbol_id=s.id
                )
                for s in symbols if s.is_exported
            ]

            raw_imports = self._extract_raw_imports(tree.root_node)
            metadata = {'lines_of_code': len(content.splitlines())}

            return symbols, exports, [], raw_imports, metadata
        except Exception:
            return [], [], [], [], {}

    def _extract_symbols(self, node, file_path: Path, content: str) -> list[CodeSymbol]:
        symbols = []
        file_path_str = str(file_path)

        def traverse(curr, parent=None):
            if 'class_declaration' in curr.type or 'function_declaration' in curr.type or 'object_declaration' in curr.type:
                name_node = None
                for child in curr.children:
                    if 'identifier' in child.type:
                        name_node = child
                        break
                if name_node:
                    name = name_node.text.decode('utf-8')
                    line_start = curr.start_point[0] + 1
                    symbol_id = UUID(
                        bytes=hashlib.sha256(f"{file_path_str}:{name}:{line_start}".encode()).digest()[:16])
                    symbol = CodeSymbol(name=name, symbol_type='class' if 'class' in curr.type else 'function',
                                        line_start=line_start, line_end=curr.end_point[0] + 1, signature=name,
                                        is_exported=True, parent=parent, id=symbol_id)
                    symbols.append(symbol)
                    for child in curr.children: traverse(child, name)
                    return
            for child in curr.children: traverse(child, parent)

        traverse(node)
        return symbols
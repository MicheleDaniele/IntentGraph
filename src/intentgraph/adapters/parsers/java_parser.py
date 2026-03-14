import hashlib
import logging
from pathlib import Path
from typing import Optional, Any
from uuid import UUID

from tree_sitter import Language as TSLanguage, Parser, Query

try:
    from tree_sitter import QueryCursor
except ImportError:
    QueryCursor = None

import tree_sitter_java
from .base import LanguageParser
from ...domain.models import CodeSymbol, APIExport

logger = logging.getLogger(__name__)


class JavaParser(LanguageParser):
    """
    Java-specific parser implementation.
    Handles AST-based symbol extraction and maps package-style imports
    to physical repository paths, with a focus on Android project structures.
    """
    def __init__(self):
        super().__init__()
        self.language = TSLanguage(tree_sitter_java.language())
        self.parser = Parser(self.language)

    def _get_file_extensions(self) -> set[str]:
        return {".java"}

    def _get_init_files(self) -> set[str]:
        return set()

    def extract_dependencies(self, file_path: Path, repo_path: Path) -> list[str]:
        """
        Extracts internal project dependencies by resolving import statements
        to actual file paths within the repository.
        """
        resolved_paths = []
        try:
            content = file_path.read_bytes()
            tree = self.parser.parse(content)
            raw_imports = self._extract_raw_imports(tree.root_node)

            for imp in raw_imports:
                resolved = self._resolve_import_path(imp, file_path, repo_path)
                resolved_paths.extend(resolved)
        except Exception:
            pass
        return list(set(resolved_paths))

    def _resolve_java_import(self, import_name: str, repo_path: Path) -> Optional[str]:
        """
        Maps a Java package notation to a relative file path.
        Heuristically searches across standard Android and Java source sets.
        """
        rel_path_str = import_name.replace('.', '/') + ".java"

        source_roots = [
            "app/src/main/java",
            "app/src/main/kotlin",
            "src/main/java"
        ]

        for root in source_roots:
            candidate = Path(root) / rel_path_str
            full_candidate = repo_path / candidate
            if full_candidate.exists():
                return str(candidate)

        return None

    def _extract_raw_imports(self, root_node) -> list[str]:
        """
        Uses Tree-sitter Queries to efficiently extract all import
        declaration identifiers from the AST.
        """
        raw_imports = []
        query = Query(self.language, "(import_declaration (scoped_identifier) @import.name)")

        if QueryCursor:
            cursor = QueryCursor(query)
            captures_dict = cursor.captures(root_node)
            for nodes in captures_dict.values():
                for node in (nodes if isinstance(nodes, list) else [nodes]):
                    raw_imports.append(node.text.decode('utf-8').strip())
        else:
            for node, _ in query.captures(root_node):
                raw_imports.append(node.text.decode('utf-8').strip())

        return list(set(raw_imports))

    def extract_code_structure(self, file_path: Path, repo_path: Path) -> tuple:
        """
        Main entry point for structural analysis.
        Returns extracted symbols, public exports, and metadata.
        """
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            tree = self.parser.parse(content.encode('utf-8'))
            symbols = self._extract_symbols(tree.root_node, file_path, content)

            raw_imports = self._extract_raw_imports(tree.root_node)

            exports = [APIExport(name=s.name, export_type=s.symbol_type, symbol_id=s.id)
                       for s in symbols if s.is_exported]

            metadata = {'lines_of_code': len(content.splitlines())}
            return symbols, exports, [], raw_imports, metadata
        except Exception as e:
            logger.error(f"Failed Java structure parse: {e}")
            return [], [], [], [], {}

    def _extract_symbols(self, node, file_path: Path, content: str) -> list[CodeSymbol]:
        """
        Recursively traverses the AST to identify key Java constructs.
        Generates stable UUIDs based on file context and line numbers.
        """
        symbols = []
        file_path_str = str(file_path)

        def traverse(curr, parent=None):
            if curr.type in ('method_declaration', 'class_declaration', 'interface_declaration'):
                name_node = curr.child_by_field_name('name')
                if name_node:
                    name = name_node.text.decode('utf-8')
                    kind = 'function' if curr.type == 'method_declaration' else 'class'
                    line_start = curr.start_point[0] + 1
                    symbol_id = UUID(
                        bytes=hashlib.sha256(f"{file_path_str}:{name}:{line_start}".encode()).digest()[:16])
                    symbol = CodeSymbol(name=name, symbol_type=kind, line_start=line_start,
                                        line_end=curr.end_point[0] + 1, signature=name, is_exported=True, parent=parent,
                                        id=symbol_id)
                    symbols.append(symbol)
                    for child in curr.children: traverse(child, name)
                    return
            for child in curr.children: traverse(child, parent)

        traverse(node)
        return symbols
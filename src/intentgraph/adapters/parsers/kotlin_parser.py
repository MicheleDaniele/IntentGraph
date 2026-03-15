import hashlib
import logging
from pathlib import Path
from typing import Optional
from uuid import UUID

from tree_sitter import Language as TSLanguage, Parser
import tree_sitter_kotlin
from .base import LanguageParser
from ...domain.models import CodeSymbol, APIExport

logger = logging.getLogger(__name__)


class KotlinParser(LanguageParser):
    def __init__(self):
        super().__init__()
        self.language = TSLanguage(tree_sitter_kotlin.language())
        self.parser = Parser(self.language)

    def _get_file_extensions(self) -> set[str]:
        return {".kt", ".kts"}

    def _get_init_files(self) -> set[str]:
        return set()

    def extract_dependencies(self, file_path: Path, repo_path: Path) -> list[str]:
        try:
            content = file_path.read_bytes()
            tree = self.parser.parse(content)
            raw_imports = self._all_imports_from_tree(tree.root_node)
            resolved = []
            for imp in raw_imports:
                res = self._resolve_kotlin_import(imp, repo_path)
                if res: resolved.append(res)
            return list(set(resolved))
        except Exception:
            return []

    def _resolve_kotlin_import(self, import_name: str, repo_path: Path) -> Optional[str]:
        clean_import = import_name.replace('.*', '').strip()
        rel_path_str = clean_import.replace('.', '/') + ".kt"
        for root in ["app/src/main/java", "app/src/main/kotlin", "src/main/kotlin"]:
            candidate = Path(root) / rel_path_str
            if (repo_path / candidate).exists(): return str(candidate)
        return None

    def _all_imports_from_tree(self, root_node) -> list[str]:
        imports = []

        def walk(node):
            if node.type in ('import_header', 'import_directive'):
                text = node.text.decode('utf-8')
                clean = text.replace('import', '').strip()
                if clean: imports.append(clean)
            for child in node.children: walk(child)

        walk(root_node)
        return list(set(imports))

    def extract_code_structure(self, file_path: Path, repo_path: Path) -> tuple:
        try:
            if not file_path.is_file(): return [], [], [], [], {}
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            tree = self.parser.parse(content.encode('utf-8'))

            raw_imports = self._all_imports_from_tree(tree.root_node)
            resolved_deps = self.extract_dependencies(file_path, repo_path)

            symbols = []
            complexity = 1
            file_path_str = str(file_path)
            comp_nodes = ('if_expression', 'for_statement', 'while_statement', 'when_entry', 'catch_clause')

            def traverse(node):
                nonlocal complexity
                if node.type in comp_nodes: complexity += 1
                if node.type in ('class_declaration', 'function_declaration', 'object_declaration'):
                    name_node = node.child_by_field_name('identifier')
                    if name_node:
                        name = name_node.text.decode('utf-8')
                        kind = 'function' if node.type == 'function_declaration' else 'class'
                        line_start = node.start_point[0] + 1
                        symbol_id = UUID(
                            bytes=hashlib.sha256(f"{file_path_str}:{name}:{line_start}".encode()).digest()[:16])
                        symbols.append(CodeSymbol(name=name, symbol_type=kind, line_start=line_start,
                                                  line_end=node.end_point[0] + 1, signature=name, is_exported=True,
                                                  id=symbol_id))
                for c in node.children: traverse(c)

            traverse(tree.root_node)
            metadata = {'lines_of_code': len(content.splitlines()), 'complexity_score': complexity,
                        'symbol_count': len(symbols)}

            return symbols, [], resolved_deps, raw_imports, metadata
        except Exception:
            return [], [], [], [], {}
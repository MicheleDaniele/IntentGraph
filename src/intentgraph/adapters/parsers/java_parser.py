import hashlib
import logging
from pathlib import Path
from typing import Optional
from uuid import UUID

from tree_sitter import Language as TSLanguage, Parser
import tree_sitter_java
from .base import LanguageParser
from ...domain.models import CodeSymbol, APIExport

logger = logging.getLogger(__name__)


class JavaParser(LanguageParser):
    def __init__(self):
        super().__init__()
        self.language = TSLanguage(tree_sitter_java.language())
        self.parser = Parser(self.language)

    def _get_file_extensions(self) -> set[str]:
        return {".java"}

    def _get_init_files(self) -> set[str]:
        return set()

    def extract_dependencies(self, file_path: Path, repo_path: Path) -> list[str]:
        try:
            content = file_path.read_bytes()
            tree = self.parser.parse(content)
            raw_imports = self._all_imports_from_tree(tree.root_node)
            resolved = []
            for imp in raw_imports:
                res = self._resolve_java_import(imp, repo_path)
                if res:
                    resolved.append(res)
            return list(set(resolved))
        except Exception:
            return []

    def _resolve_java_import(self, import_name: str, repo_path: Path) -> Optional[str]:
        clean_import = import_name.replace('.*', '').strip()
        rel_path_str = clean_import.replace('.', '/') + ".java"
        source_roots = ["app/src/main/java", "app/src/main/kotlin", "src/main/java"]
        for root in source_roots:
            candidate = Path(root) / rel_path_str
            if (repo_path / candidate).exists():
                return str(candidate)
        return None

    def extract_code_structure(self, file_path: Path, repo_path: Path) -> tuple:
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            tree = self.parser.parse(content.encode('utf-8'))

            # Estrazione Import Manuale
            raw_imports = []
            for child in tree.root_node.children:
                if child.type == 'import_declaration':
                    for sub in child.children:
                        if sub.type in ('scoped_identifier', 'identifier', 'asterisk_import'):
                            raw_imports.append(sub.text.decode('utf-8').strip())

            # Simboli e Complessità
            symbols = []
            complexity = 1
            file_path_str = str(file_path)
            comp_nodes = ('if_statement', 'for_statement', 'while_statement', 'catch_clause', 'switch_label')

            def traverse(node, parent_name=None):
                nonlocal complexity
                if node.type in comp_nodes: complexity += 1
                if node.type in ('method_declaration', 'class_declaration', 'interface_declaration'):
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        name = name_node.text.decode('utf-8')
                        kind = 'function' if node.type == 'method_declaration' else 'class'
                        line_start = node.start_point[0] + 1
                        symbol_id = UUID(
                            bytes=hashlib.sha256(f"{file_path_str}:{name}:{line_start}".encode()).digest()[:16])
                        symbols.append(CodeSymbol(name=name, symbol_type=kind, line_start=line_start,
                                                  line_end=node.end_point[0] + 1, signature=name, is_exported=True,
                                                  id=symbol_id))
                        for c in node.children: traverse(c, name)
                        return
                for c in node.children: traverse(c, parent_name)

            traverse(tree.root_node)
            exports = [APIExport(name=s.name, export_type=s.symbol_type, symbol_id=s.id) for s in symbols]

            metadata = {
                'lines_of_code': len(content.splitlines()),
                'complexity_score': complexity,
                'symbol_count': len(symbols)
            }

            return symbols, exports, [], list(set(raw_imports)), metadata

        except Exception as e:
            logger.error(f"Failed Java parse: {e}")
            return [], [], [], [], {}
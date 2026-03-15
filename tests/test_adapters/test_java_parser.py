import pytest
from pathlib import Path
from uuid import UUID
import tempfile
import shutil
from intentgraph.adapters.parsers.java_parser import JavaParser


@pytest.fixture
def java_parser():
    return JavaParser()


@pytest.fixture
def tmp_repo():
    path = Path(tempfile.mkdtemp())
    yield path
    shutil.rmtree(path)


class TestJavaParserUltimate:
    def test_full_logic_coverage(self, java_parser, tmp_repo):
        # Il tuo parser calcola: 1 (base) + 1 (if) + 1 (while) + 1 (catch) = 4
        code = """
        package com.test;
        public interface ITest { void run(); }
        public class MyClass {
            public void test(int x) {
                if (x > 0) { 
                    while(x < 10) { x++; }
                    try { throw new Exception(); } catch(Exception e) {}
                }
            }
        }
        """
        f = tmp_repo / "Full.java"
        f.write_text(code)
        # Il tuo parser restituisce: symbols, exports, [], imports, metadata
        symbols, exports, function_deps, imports, metadata = java_parser.extract_code_structure(f, tmp_repo)

        assert metadata['complexity_score'] >= 4
        assert len(symbols) >= 3
        assert "com.test" not in imports  # Gli import sono quelli che iniziano con 'import'

    def test_import_extraction_logic(self, java_parser, tmp_repo):
        # Testiamo l'estrazione degli import (quarta posizione del return)
        code = """
        import android.os.Bundle;
        import nic.goi.aarogyasetu.GattServer;
        public class Main {}
        """
        f = tmp_repo / "Main.java"
        f.write_text(code)
        _, _, _, imports, _ = java_parser.extract_code_structure(f, tmp_repo)

        assert "android.os.Bundle" in imports
        assert "nic.goi.aarogyasetu.GattServer" in imports

    def test_resolve_java_import_utility(self, java_parser, tmp_repo):
        # Testiamo direttamente il metodo di risoluzione per la coverage
        pkg_dir = tmp_repo / "app/src/main/java/com/pkg"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "Dep.java").write_text("package com.pkg; class Dep {}")

        resolved = java_parser._resolve_java_import("com.pkg.Dep", tmp_repo)
        assert resolved == "app/src/main/java/com/pkg/Dep.java"

    def test_error_handling_graceful(self, java_parser, tmp_repo):
        # Passiamo una directory invece di un file per forzare il blocco 'except'
        # e verificare che restituisca i valori vuoti come da tuo codice
        symbols, exports, deps, imports, metadata = java_parser.extract_code_structure(tmp_repo, tmp_repo)
        assert symbols == []
        assert metadata == {}

    def test_deterministic_ids(self, java_parser, tmp_repo):
        # Verifica che gli ID generati siano stabili
        f = tmp_repo / "A.java"
        f.write_text("class A { void b() {} }")
        s1, _, _, _, _ = java_parser.extract_code_structure(f, tmp_repo)
        s2, _, _, _, _ = java_parser.extract_code_structure(f, tmp_repo)
        assert s1[0].id == s2[0].id
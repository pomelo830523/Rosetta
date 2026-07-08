"""graph_db:schema 檢查、symbol 查詢、呼叫關係、file hash(以假 codegraph.db)。"""

import graph_db

_NODES = [
    ("n1", "method", "calcFee", "demo::OrderService::calcFee", "src/A.java", 10, 20, "int calcFee()"),
    ("n2", "method", "toDto", "demo::OrderService::toDto", "src/A.java", 30, 40, "Dto toDto()"),
    ("n3", "class", "OrderService", "demo::OrderService", "src/A.java", 1, 50, ""),
    ("n4", "import", "java.util", "java.util", "src/A.java", 1, 1, ""),  # 不可索引
]
_EDGES = [
    ("n2", "n1", "calls"),
    ("n3", "n1", "contains"),   # 非 calls/references/instantiates,應被濾掉
]
_FILES = [("src/A.java", "hash-a"), ("src/B.java", "hash-b")]


def _app_with_graph(make_app, make_codegraph, version=6):
    app = make_app()
    make_codegraph(app, nodes=_NODES, edges=_EDGES, files=_FILES,
                   schema_version=version)
    return app


class TestAvailability:
    def test_available_false_without_db(self, make_app):
        assert not graph_db.available(make_app())

    def test_available_true_with_db(self, make_app, make_codegraph):
        assert graph_db.available(_app_with_graph(make_app, make_codegraph))


class TestSchemaWarning:
    def test_tested_version_no_warning(self, make_app, make_codegraph):
        app = _app_with_graph(make_app, make_codegraph)
        assert graph_db.schema_warning(app) == ""

    def test_other_version_warns(self, make_app, make_codegraph):
        app = _app_with_graph(make_app, make_codegraph, version=99)
        assert "version=99" in graph_db.schema_warning(app)


class TestQueries:
    def test_iter_symbols_filters_kinds(self, make_app, make_codegraph):
        app = _app_with_graph(make_app, make_codegraph)
        names = {s.name for s in graph_db.iter_symbols(app)}
        assert names == {"calcFee", "toDto", "OrderService"}

    def test_find_nodes_substring_case_insensitive(self, make_app, make_codegraph):
        app = _app_with_graph(make_app, make_codegraph)
        nodes = graph_db.find_nodes("CALCFEE", app)
        assert [n.node_id for n in nodes] == ["n1"]

    def test_find_nodes_limit(self, make_app, make_codegraph):
        app = _app_with_graph(make_app, make_codegraph)
        assert len(graph_db.find_nodes("o", app, limit=1)) == 1

    def test_callers_only_call_like_edges(self, make_app, make_codegraph):
        app = _app_with_graph(make_app, make_codegraph)
        callers = graph_db.callers("n1", app)
        assert [(k, s.name) for k, s in callers] == [("calls", "toDto")]

    def test_callees(self, make_app, make_codegraph):
        app = _app_with_graph(make_app, make_codegraph)
        callees = graph_db.callees("n2", app)
        assert [s.name for _, s in callees] == ["calcFee"]

    def test_file_hashes(self, make_app, make_codegraph):
        app = _app_with_graph(make_app, make_codegraph)
        assert graph_db.file_hashes(app) == {"src/A.java": "hash-a",
                                             "src/B.java": "hash-b"}

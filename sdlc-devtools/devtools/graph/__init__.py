"""The code-graph subsystem: the extracted model, the fitness gate over it, and the viz that renders it.

Unlike the domain folders beside it, this one is grouped by genuine CO-USE (bd yfv.2 / 5hg). `classes` (the
class/method index), `calls` (the behavioural call arrows) and `arrows` (the structural dependency arrows)
are the shared read-models; `fitness` (the import-graph gates: god-module / cycle / god-file / test-mirror)
and `archmap` (the graph.json + HTML viewer) are the only two modules that consume ALL THREE. The coupling
gates read the model too, but partially and from outside — they build ON the graph, they are not OF it.

`fitness.py` was `graph.py`: a module named `graph` cannot live in a package named `graph`, and the rename
says what the module actually is (the arch-FITNESS gate) rather than restating the folder.
"""

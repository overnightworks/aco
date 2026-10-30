"""The operator's decision board.

`aco serve` shows this repository's open expectation lines as cards and
writes the operator's choice back as a ruling. It reads and writes through
aco's own library in process; only `aco_source` reaches aco's session and
ruling writer.
"""

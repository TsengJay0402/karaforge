# Local type stubs

Minimal `.pyi` stubs for third-party packages that ship without type information, covering
only the functions KaraForge calls. They exist so that `pyright` can run in strict mode
without per-line ignores. They contain no runtime code and are not part of the wheel.

# Vendored IHP SRAM simulation models

Unmodified copies of two files from the IHP-Open-PDK (Apache-2.0), commit
`2bbec755dc67ca3db0261c3d6163e15735d66710`, path `ihp-sg13cmos5l/libs.ref/sg13cmos5l_sram/verilog/`:

- `RM_IHPSG13_1P_512x16_c2_bm_bist.v` -- the macro wrapper (instantiates the behavioural core under `FUNCTIONAL`; checks `A_DLY == 1`)
- `RM_IHPSG13_1P_core_behavioral_bm_bist.v` -- the behavioural single-port SRAM

They are here because the GitHub `test` and `gl_test` jobs have no PDK checkout, and because the
gate-level netlist keeps the macro as a black box. Every `test/Makefile*` adds both with `-DFUNCTIONAL`.
The synthesis view is the port-only `src/RM_IHPSG13_1P_512x16_c2_bm_bist.v`.

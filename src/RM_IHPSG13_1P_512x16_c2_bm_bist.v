`default_nettype none
// Port-only black box of the IHP SG13CMOS5L single-port SRAM macro RM_IHPSG13_1P_512x16_c2_bm_bist.
// Synthesis view only: src/config.json names it in MACROS.nl. It is NOT in info.yaml source_files
// and NOT in any test Makefile -- simulation uses the PDK behavioural model in test/models/.
// Do not add a body: with one, LibreLane would synthesise 8,192 flip-flops instead of placing the macro.
/* verilator lint_off UNUSEDSIGNAL */
/* verilator lint_off UNDRIVEN */
(* blackbox *)
module RM_IHPSG13_1P_512x16_c2_bm_bist (
    input  wire        A_CLK,
    input  wire        A_MEN,
    input  wire        A_WEN,
    input  wire        A_REN,
    input  wire [8:0]  A_ADDR,
    input  wire [15:0] A_DIN,
    input  wire        A_DLY,
    output wire [15:0] A_DOUT,
    input  wire [15:0] A_BM,
    input  wire        A_BIST_CLK,
    input  wire        A_BIST_EN,
    input  wire        A_BIST_MEN,
    input  wire        A_BIST_WEN,
    input  wire        A_BIST_REN,
    input  wire [8:0]  A_BIST_ADDR,
    input  wire [15:0] A_BIST_DIN,
    input  wire [15:0] A_BIST_BM
);
endmodule
/* verilator lint_on UNDRIVEN */
/* verilator lint_on UNUSEDSIGNAL */

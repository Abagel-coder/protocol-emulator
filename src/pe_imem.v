`default_nettype none
// Instruction memory, 512 x 16, synchronous read (one-cycle latency), host write port.
// IMPL = "MACRO": one IHP RM_IHPSG13_1P_512x16_c2_bm_bist single-port SRAM (the chip).
// IMPL = "FLOPS": a flip-flop array with the same cycle behaviour (fallback: a flow failure, FPGA).
// The single port is shared. A host write is accepted only while the core is not active; a write
// that arrives while the core is active is dropped and reported for that cycle on wr_dropped
// (pe_host_spi keeps it as READ_STATUS bit 5). During an accepted write the read output holds its
// previous word (A_REN low: no write-through), so a paused core's stalled instruction word is
// unchanged when RUN returns (unless a write is accepted in the last inactive cycle, which only the
// asynchronous RUN pin rising during a WRITE_IMEM can do: ir then holds the old word for the first
// active cycle and the new one after; load with RUN low); the next cycle reads raddr again. Address bit 9 is ignored:
// addresses alias modulo 512. Contents are undefined at power-up: load before RUN.
module pe_imem #(
    parameter IMPL = "MACRO"
) (
    input  wire        clk,
    input  wire        active,
    input  wire [9:0]  raddr,
    output wire [15:0] rdata,
    input  wire        wr_en,
    input  wire [9:0]  waddr,
    input  wire [15:0] wdata,
    output wire        wr_dropped
);
  wire wr_ok = wr_en && !active;
  assign wr_dropped = wr_en && active;
  wire [8:0] addr = wr_ok ? waddr[8:0] : raddr[8:0];
  generate
    if (IMPL == "MACRO") begin : g_macro
      RM_IHPSG13_1P_512x16_c2_bm_bist u_sram (
          .A_CLK(clk), .A_MEN(1'b1), .A_WEN(wr_ok), .A_REN(!wr_ok), .A_ADDR(addr), .A_DIN(wdata),
          .A_DLY(1'b1), .A_DOUT(rdata), .A_BM(16'hFFFF),
          .A_BIST_CLK(1'b0), .A_BIST_EN(1'b0), .A_BIST_MEN(1'b0), .A_BIST_WEN(1'b0), .A_BIST_REN(1'b0),
          .A_BIST_ADDR(9'd0), .A_BIST_DIN(16'd0), .A_BIST_BM(16'd0));
    end else begin : g_flops
      reg [15:0] mem [0:511];
      reg [15:0] rdata_q;
      always @(posedge clk) begin
        if (wr_ok) mem[addr] <= wdata;
        else rdata_q <= mem[addr];
      end
      assign rdata = rdata_q;
    end
  endgenerate
  wire _unused = &{raddr[9], waddr[9], 1'b0};
endmodule

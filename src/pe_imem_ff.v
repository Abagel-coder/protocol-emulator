`default_nettype none
// Flip-flop instruction memory, synchronous read (one-cycle latency), host write port.
module pe_imem_ff #(
    parameter integer WORDS = 64,
    parameter integer AW = 6
) (
    input  wire        clk,
    input  wire [9:0]  raddr,
    output reg  [15:0] rdata,
    input  wire        wr_en,
    input  wire [9:0]  waddr,
    input  wire [15:0] wdata
);
  reg [15:0] mem [0:WORDS-1];
  always @(posedge clk) begin
    if (wr_en) mem[waddr[AW-1:0]] <= wdata;
    rdata <= mem[raddr[AW-1:0]];
  end
  // raddr/waddr are sized for the 10-bit pc/imem_waddr busses in the top level, but this
  // memory only has WORDS=2**AW entries; the bits above AW simply address beyond the actual
  // depth and are unused here (not an error condition, just headroom in the shared bus width).
  wire _unused = &{raddr[9:AW], waddr[9:AW], 1'b0};
endmodule

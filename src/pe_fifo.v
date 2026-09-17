`default_nettype none
// 4-entry, 16-bit FIFO. Push when full and pop when empty are ignored.
module pe_fifo (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        push,
    input  wire [15:0] wdata,
    input  wire        pop,
    output wire [15:0] rdata,
    output wire        valid,
    output wire        full
);
  reg [15:0] mem [0:3];
  reg [2:0] wp, rp;
  wire empty = (wp == rp);
  assign full  = (wp[2] != rp[2]) && (wp[1:0] == rp[1:0]);
  assign valid = !empty;
  assign rdata = mem[rp[1:0]];
  always @(posedge clk) begin
    if (!rst_n) begin
      wp <= 3'd0; rp <= 3'd0;
    end else begin
      if (push && !full) begin mem[wp[1:0]] <= wdata; wp <= wp + 3'd1; end
      if (pop && !empty) rp <= rp + 3'd1;
    end
  end
endmodule

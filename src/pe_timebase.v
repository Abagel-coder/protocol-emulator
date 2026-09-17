`default_nettype none
// Free-running 16-bit timebase T with an 8-bit prescaler (divide by prescale+1).
module pe_timebase (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        en,
    input  wire [7:0]  prescale,
    output reg  [15:0] t_out,
    output wire        tick
);
  reg [7:0] cnt;
  assign tick = en && (cnt == prescale);
  always @(posedge clk) begin
    if (!rst_n) begin
      cnt <= 8'd0; t_out <= 16'd0;
    end else if (en) begin
      if (cnt == prescale) begin
        cnt <= 8'd0; t_out <= t_out + 16'd1;
      end else begin
        cnt <= cnt + 8'd1;
      end
    end
  end
endmodule

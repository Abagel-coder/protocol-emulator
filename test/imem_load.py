"""Deposit a program straight into the simulated instruction memory (RTL simulations without a host).
The chip's memory is the IHP macro; its behavioural model (test/models) keeps the words in
`<u_imem>.g_macro.u_sram.i_SRAM_1P_behavioral_bm_bist.memory`. Unwritten words are set to 0 so a
simulated core never fetches X; on silicon they are random, so the host loads everything before RUN."""
IMEM_WORDS = 512

def imem_array(imem):
    return imem.g_macro.u_sram.i_SRAM_1P_behavioral_bm_bist.memory

def load_imem(imem, words):
    assert len(words) <= IMEM_WORDS, len(words)
    mem = imem_array(imem)
    for i in range(IMEM_WORDS):
        mem[i].value = words[i] if i < len(words) else 0

# SPDX-FileCopyrightText: © 2026 anbaghel
# SPDX-License-Identifier: Apache-2.0
"""The warm-up UART transmitter is no longer wired to the top-level pins (see
src/project.v and src/pe_host_spi.v). Its three directed tests lived here;
they are gone because the fixed UART is off the pins. A fixed-firmware UART
test lands in test/test_uart_fw.py under Task 8. test/test_host.py covers
the SPI loader that replaced this warm-up path.
"""

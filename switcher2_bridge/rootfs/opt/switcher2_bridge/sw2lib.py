#!/usr/bin/env python3
"""
sw2lib.py — switcher2 Modbus RTU library.

Provides a complete API for interacting with the switcher2 firmware via Modbus RTU,
including both transport layer and device-specific command implementations.
"""

import sys
import time
from pymodbus.client import ModbusSerialClient

# ── Constants ──────────────────────────────────────────────────────────────────
DEFAULT_PORT     = '/dev/ttyUSB0'
DEFAULT_BAUD     = 19200
DEFAULT_SLAVE    = 22
DEFAULT_PARITY   = 'E'   # Even parity (8E1 is Modbus standard)
DEFAULT_BYTESIZE = 8
DEFAULT_STOPBITS = 1
TIMEOUT_S        = 1.0   # must exceed largest frame TX time (249 bytes @ 19200 = ~130 ms)

# Firmware constants
CHANNEL_MAX    = 14
RELAY_MAX      = CHANNEL_MAX
INPUT_MAX      = 16
BUTTON_EVENT_COUNT = 4

# Holding-register map
HR_DEVICE_VER   =   0
HR_CONFIG_SAVE  =   1
HR_CONFIG_RESET =   2
HR_CONFIG_DISC  =   3
HR_CONFIG_DIRTY  =   4
HR_BUILD_HASH_LO =   5   # git hash bits [15:0]
HR_BUILD_HASH_HI =   6   # git hash bits [31:16]
HR_BUILD_TS_LO   =   7   # build unix timestamp bits [15:0]
HR_BUILD_TS_HI   =   8   # build unix timestamp bits [31:16]
HR_FW_VERSION    =   9   # (major << 8) | minor — matches pico_set_binary_version
HR_CH_CMD_BASE   =  10
HR_CH_CFG_BASE  = 100
CH_CFG_SIZE     = 9    # registers per channel in HR_CH_CFG_BASE area
HR_DEBOUNCE_BASE= 300
HR_ACTION_BASE  = 350
HR_ZCD_GLOBAL   = 650
HR_ZCD_DELAY_BASE = HR_ZCD_GLOBAL + 1
HR_ZCD_PENDING_BASE = HR_ZCD_DELAY_BASE + RELAY_MAX
HR_ZCD_EDGE_COUNT = HR_ZCD_PENDING_BASE + RELAY_MAX
HR_ZCD_EDGE_AGE_MS = HR_ZCD_EDGE_COUNT + 1
HR_ZCD_FALLBACK_COUNT = HR_ZCD_EDGE_AGE_MS + 1

# Discrete-input map
DI_INPUT_BASE   =   0
DI_RELAY_BASE   = 100

# Input-register map
IR_STATUS_BASE  =   0
IR_MOTION_BASE  =  50
IR_TEMP_BASE    = 200   # 5 sensors; value in 0.1°C signed units, 0x8000 = no reading

SENSOR_MAX           = 5
SENSOR_CHIP_TEMP_IDX = 4   # slot 4 = RP2350 internal ADC sensor (not an LM75)
TEMP_NO_READING = 0x8000  # sentinel returned by firmware when no sample yet

# Action / channel types
CH_TYPES   = {0: 'unassigned', 1: 'light', 2: 'blind'}
CH_TYPES_R = {v: k for k, v in CH_TYPES.items()}

ACTIONS = {
    0: 'none',
    1: 'toggle',
    2: 'set_on',
    3: 'set_off',
    4: 'blind_set_pos',
    5: 'blind_move_open',
    6: 'blind_move_closed',
    7: 'blind_stop',
}
ACTIONS_R = {v: k for k, v in ACTIONS.items()}

EVENT_NAMES = ['press', 'release', 'short', 'long']
MOTION_NAMES = {0: 'idle', 1: 'opening', 2: 'closing'}

SAVE_MAGIC = 0x5A5A

# OTA register map
HR_SDK_VERSION   = 503   # (sdk_major << 8) | sdk_minor — from pico/version.h
HR_SYS_REBOOT    = 504   # write 0x5A5A → watchdog reboot
HR_TRIAL_BOOT    = 500
HR_OTA_SLOT      = 501
HR_OTA_BUY_PEND  = 502
HR_OTA_SIZE_LO   = 505
HR_OTA_SIZE_HI   = 506
HR_OTA_CMD       = 507
HR_OTA_STATUS    = 508
HR_OTA_WR_LO     = 509
HR_OTA_DATA      = 510
HR_OTA_DATA_REGS = 120   # max registers per FC16 write (240 bytes)

OTA_STATUS_NAMES = {0: 'idle', 1: 'erasing', 2: 'active', 3: 'done', 4: 'error'}
OTA_CMD_BEGIN    = 1
OTA_CMD_FINISH   = 2
OTA_CMD_ABORT    = 3
OTA_CMD_CONFIRM  = 4

EXCEPTION_CODES = {
    1: 'ILLEGAL_FUNCTION',
    2: 'ILLEGAL_DATA_ADDRESS',
    3: 'ILLEGAL_DATA_VALUE',
    4: 'SLAVE_DEVICE_FAILURE',
}


# ── Modbus RTU transport ──────────────────────────────────────────────────────
class ModbusError(Exception):
    """Exception raised for Modbus communication errors."""
    pass


class Modbus:
    """Modbus RTU client for switcher2 board."""

    def __init__(self, port: str = DEFAULT_PORT, baud: int = DEFAULT_BAUD,
                 slave: int = DEFAULT_SLAVE, parity: str = DEFAULT_PARITY,
                 bytesize: int = DEFAULT_BYTESIZE, stopbits: int = DEFAULT_STOPBITS):
        """Initialize Modbus connection.

        Args:
            port:     Serial port (e.g., '/dev/ttyUSB0')
            baud:     Baud rate (default 19200)
            slave:    Modbus slave address (default 22)
            parity:   'E' (even), 'O' (odd), 'N' (none) — default 'E'
            bytesize: Data bits (default 8)
            stopbits: Stop bits (default 1)
        """
        self._slave = slave
        self._client = ModbusSerialClient(
            port=port,
            framer='rtu',
            baudrate=baud,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
            timeout=TIMEOUT_S,
        )
        if not self._client.connect():
            raise ModbusError(f"Cannot connect to {port}")

    def close(self):
        """Close the Modbus connection."""
        self._client.close()

    def _check_exception(self, response, func_code: int):
        """Check for Modbus exception responses.

        Handles both pymodbus 3.x naming conventions:
        - is_error() used in some versions
        - isError() used in pymodbus 3.12+
        """
        is_err = (
            (hasattr(response, 'is_error') and response.is_error()) or
            (hasattr(response, 'isError') and response.isError())
        )
        if is_err:
            code = getattr(response, 'exception_code', 0)
            raise ModbusError(
                f"Exception FC=0x{func_code:02X} code={code} "
                f"({EXCEPTION_CODES.get(code, 'unknown')})"
            )

    def _call(self, fn, *args, **kwargs):
        """Call a pymodbus client method, re-raising any IO exception as ModbusError."""
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            # ModbusIOException and similar are raised directly by pymodbus on
            # timeout / no-response — wrap them so callers see ModbusError.
            raise ModbusError(str(e)) from e

    # FC 03 — Read Holding Registers
    def read_hr(self, addr: int, count: int) -> list[int]:
        resp = self._call(self._client.read_holding_registers,
                          address=addr, count=count, device_id=self._slave)
        self._check_exception(resp, 0x03)
        return list(resp.registers)

    # FC 06 — Write Single Holding Register
    def write_hr(self, addr: int, value: int) -> None:
        resp = self._call(self._client.write_register,
                          address=addr, value=value, device_id=self._slave)
        self._check_exception(resp, 0x06)

    # FC 16 — Write Multiple Holding Registers
    def write_hrs(self, addr: int, values: list[int]) -> None:
        resp = self._call(self._client.write_registers,
                          address=addr, values=values, device_id=self._slave)
        self._check_exception(resp, 0x10)

    # FC 02 — Read Discrete Inputs
    def read_di(self, addr: int, count: int) -> list[bool]:
        resp = self._call(self._client.read_discrete_inputs,
                          address=addr, count=count, device_id=self._slave)
        self._check_exception(resp, 0x02)
        result = resp.bits[:count]
        return [bool(b) for b in result]

    # FC 04 — Read Input Registers
    def read_ir(self, addr: int, count: int) -> list[int]:
        resp = self._call(self._client.read_input_registers,
                          address=addr, count=count, device_id=self._slave)
        self._check_exception(resp, 0x04)
        return list(resp.registers)


# ── Device-specific command implementations ───────────────────────────────────
def do_info(mb: Modbus, _args):
    """Show firmware version, build identity, and config dirty flag."""
    from datetime import datetime, timezone
    regs     = mb.read_hr(HR_DEVICE_VER, 10)   # HR 0-9
    sdk_regs = mb.read_hr(HR_SDK_VERSION, 1)
    ver      = regs[HR_DEVICE_VER]
    dirty    = regs[HR_CONFIG_DIRTY]
    git_hash = (regs[HR_BUILD_HASH_HI] << 16) | regs[HR_BUILD_HASH_LO]
    build_ts = (regs[HR_BUILD_TS_HI]   << 16) | regs[HR_BUILD_TS_LO]
    fw_ver   = regs[HR_FW_VERSION]
    sdk_ver  = sdk_regs[0]
    fw_major, fw_minor   = fw_ver >> 8, fw_ver & 0xFF
    sdk_major, sdk_minor = sdk_ver >> 8, sdk_ver & 0xFF
    print(f"Firmware version : {ver}")
    print(f"Image version    : {fw_major}.{fw_minor}")
    print(f"Pico SDK         : {sdk_major}.{sdk_minor}")
    print(f"Git hash         : {git_hash:08x}")
    if build_ts:
        dt = datetime.fromtimestamp(build_ts, tz=timezone.utc)
        print(f"Build time       : {dt.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Config dirty     : {'YES — unsaved changes in RAM' if dirty else 'no'}")


def relay_mask_to_str(mask: int) -> str:
    relays = [str(i + 1) for i in range(64) if mask & (1 << i)]
    return ', '.join(relays) if relays else '—'


def _channel_row(ch: int, regs: list[int], status: int, motion: int) -> str:
    """Format a single channel row for listing."""
    typ, f1, f2, f3, f4, t_open, t_close, off_delay, default_on = regs
    type_s  = CH_TYPES.get(typ, f'?{typ}')
    if typ == 1:
        relay_mask = f1 | (f2 << 16) | (f3 << 32) | (f4 << 48)
        relay_s = relay_mask_to_str(relay_mask)
        rb_s    = '-'
        st = 'ON' if status else 'off'
        to_s = tc_s = '-'
        od_s = f'{off_delay}s' if off_delay else 'off'
        def_s = 'on' if default_on else 'off'
    elif typ == 2:
        relay_s = str(f1) if f1 else '-'
        rb_s    = str(f2) if f2 else '-'
        st   = (f'{status / 100:.0f}%' if status != 0xFFFF else 'uncal') + \
               f' {MOTION_NAMES.get(motion, "?")}'
        to_s = str(t_open)
        tc_s = str(t_close)
        od_s = def_s = '-'
    else:
        relay_s = rb_s = '-'
        st = to_s = tc_s = od_s = def_s = '-'
    return f"{ch:>2}  {type_s:<12}  {relay_s:>14}  {rb_s:>7}  {to_s:>8}  {tc_s:>9}  {od_s:>8}  {def_s:>7}  {st}"


def read_all_channel_cfgs(mb: Modbus) -> list[int]:
    """Read all channel config registers, chunked to stay within the Modbus 125-register limit."""
    half = CHANNEL_MAX // 2  # 7 channels per chunk (7*9=63 regs each)
    a = mb.read_hr(HR_CH_CFG_BASE, half * CH_CFG_SIZE)
    b = mb.read_hr(HR_CH_CFG_BASE + half * CH_CFG_SIZE, (CHANNEL_MAX - half) * CH_CFG_SIZE)
    return a + b


def do_channel_list(mb: Modbus, _args):
    """List all channel configurations and status."""
    cfgs   = read_all_channel_cfgs(mb)
    status = mb.read_ir(IR_STATUS_BASE, CHANNEL_MAX)
    motion = mb.read_ir(IR_MOTION_BASE, CHANNEL_MAX)
    print(f"{'Ch':>2}  {'Type':<12}  {'Relays/Relay A':>14}  {'Relay B':>7}  {'Open ms':>8}  {'Close ms':>9}  {'Off dly':>8}  {'Default':>7}  Status")
    print('─' * 101)
    for ch in range(CHANNEL_MAX):
        s = ch * CH_CFG_SIZE
        print(_channel_row(ch, cfgs[s : s + CH_CFG_SIZE], status[ch], motion[ch]))


def do_channel_set(mb: Modbus, args):
    """Configure a channel."""
    ch = args.channel
    base = HR_CH_CFG_BASE + ch * CH_CFG_SIZE
    cur  = mb.read_hr(base, CH_CFG_SIZE)
    typ, f1, f2, f3, f4, t_open, t_close, off_delay, default_on = cur
    if args.type       is not None: typ        = CH_TYPES_R[args.type]
    if args.open_ms    is not None: t_open     = args.open_ms
    if args.close_ms   is not None: t_close    = args.close_ms
    if args.off_delay  is not None: off_delay  = args.off_delay
    if args.default_on is not None: default_on = 1 if args.default_on else 0
    # Determine relay fields
    if typ == 1:  # light
        relay_mask = f1 | (f2 << 16) | (f3 << 32) | (f4 << 48)
        if getattr(args, 'relays', None) is not None:
            relay_mask = 0
            for r in args.relays.split(','):
                n = int(r.strip())
                if 1 <= n <= 64:
                    relay_mask |= (1 << (n - 1))
        elif args.relay_a is not None:
            # backward compat: treat single relay number as a mask
            n = args.relay_a
            relay_mask = (1 << (n - 1)) if 1 <= n <= 64 else 0
        f1 = relay_mask & 0xFFFF
        f2 = (relay_mask >> 16) & 0xFFFF
        f3 = (relay_mask >> 32) & 0xFFFF
        f4 = (relay_mask >> 48) & 0xFFFF
    else:
        relay_mask = 0
        if args.relay_a is not None: f1 = args.relay_a
        if args.relay_b is not None: f2 = args.relay_b
    mb.write_hrs(base, [typ, f1, f2, f3, f4, t_open, t_close, off_delay, default_on])
    if typ == 1:
        print(f"Channel {ch}: type={CH_TYPES.get(typ)} relays={relay_mask_to_str(relay_mask)} "
              f"off_delay={off_delay}s default={'on' if default_on else 'off'}")
    else:
        print(f"Channel {ch}: type={CH_TYPES.get(typ)} relay_a={f1} relay_b={f2} "
              f"open={t_open}ms close={t_close}ms off_delay={off_delay}s "
              f"default={'on' if default_on else 'off'}")


def do_channel_cmd(mb: Modbus, args):
    """Send a command to a channel."""
    ch  = args.channel
    cmd = args.cmd
    reg = HR_CH_CMD_BASE + ch
    if   cmd == 'on':        mb.write_hr(reg, 1)
    elif cmd == 'off':       mb.write_hr(reg, 0)
    elif cmd == 'toggle':    mb.write_hr(reg, 2)
    elif cmd == 'stop':      mb.write_hr(reg, 10001)
    elif cmd == 'calibrate': mb.write_hr(reg, 10002)
    elif cmd.startswith('pos='):
        try:
            pos = int(cmd[4:])
            assert 0 <= pos <= 10000
        except (ValueError, AssertionError):
            sys.exit("Error: pos= requires integer 0–10000")
        mb.write_hr(reg, pos)
    else:
        sys.exit(f"Unknown command '{cmd}'. Use: on/off/toggle/stop/calibrate/pos=N")
    print(f"Channel {ch}: '{cmd}' sent OK")


def do_config(mb: Modbus, args):
    """Persist / reset / discard config."""
    op = args.op
    if op == 'save':
        mb.write_hr(HR_CONFIG_SAVE, SAVE_MAGIC)
        print("Saving to flash...", end=' ', flush=True)
        time.sleep(0.4)   # flash erase+write ~50 ms; be generous
        dirty = mb.read_hr(HR_CONFIG_DIRTY, 1)[0]
        print(f"done. Dirty flag now: {'YES (save failed?)' if dirty else 'no — persisted OK'}")
    elif op == 'reset':
        mb.write_hr(HR_CONFIG_RESET, SAVE_MAGIC)
        print("Factory reset and saved to flash")
    elif op == 'discard':
        mb.write_hr(HR_CONFIG_DISC, SAVE_MAGIC)
        print("Unsaved changes discarded — reloaded from flash")


def do_inputs(mb: Modbus, _args):
    """Show physical input and relay states."""
    inputs = mb.read_di(DI_INPUT_BASE, INPUT_MAX)
    relays = mb.read_di(DI_RELAY_BASE, CHANNEL_MAX)
    print("Physical inputs  (1=pressed):")
    for i, v in enumerate(inputs):
        if v:
            print(f"  Input {i+1:>2}: PRESSED")
    pressed = sum(inputs)
    if not pressed:
        print("  (all idle)")
    print("\nRelay states  (1=energised):")
    for i, v in enumerate(relays):
        print(f"  Relay {i+1:>2}: {'ON ' if v else 'off'}", end='  ')
        if (i + 1) % 4 == 0:
            print()
    print()


def do_action_list(mb: Modbus, args):
    """List action mappings."""
    inp_filter = (args.input - 1) if args.input is not None else None  # → 0-based
    inputs = [inp_filter] if inp_filter is not None else range(INPUT_MAX)
    show_empty = inp_filter is not None

    header = f"{'Input':>5}  {'Event':<8}  {'Action':<18}  {'Ch':>4}  Param"
    printed_header = False

    for inp in inputs:
        base = HR_ACTION_BASE + inp * BUTTON_EVENT_COUNT * 3
        regs = mb.read_hr(base, BUTTON_EVENT_COUNT * 3)
        for ev in range(BUTTON_EVENT_COUNT):
            action  = regs[ev * 3]
            channel = regs[ev * 3 + 1]
            param   = regs[ev * 3 + 2]
            if action == 0 and not show_empty:
                continue
            if not printed_header:
                print(header)
                print('─' * 52)
                printed_header = True
            ev_s  = EVENT_NAMES[ev] if ev < len(EVENT_NAMES) else str(ev)
            ch_s  = str(channel) if channel else '-'
            pa_s  = str(param)   if action == 4 else '-'
            print(f"{inp+1:>5}  {ev_s:<8}  {ACTIONS.get(action, f'?{action}'):<18}  {ch_s:>4}  {pa_s}")

    if not printed_header:
        print("(no actions configured)")


def do_action_set(mb: Modbus, args):
    """Set an action mapping."""
    inp = args.input - 1   # → 0-based
    ev  = args.event
    if not 0 <= inp < INPUT_MAX:
        sys.exit(f"Error: input must be 1–{INPUT_MAX}")
    if not 0 <= ev < BUTTON_EVENT_COUNT:
        sys.exit(f"Error: event must be 0–{BUTTON_EVENT_COUNT-1}  (0=press 1=release 2=short 3=long)")

    action = ACTIONS_R.get(args.action)
    if action is None:
        try:
            action = int(args.action)
        except ValueError:
            sys.exit(f"Error: unknown action '{args.action}'. Options: {', '.join(ACTIONS_R)}")

    channel = args.channel if args.channel is not None else 0
    param   = args.param   if args.param   is not None else 0

    base = HR_ACTION_BASE + inp * BUTTON_EVENT_COUNT * 3 + ev * 3
    mb.write_hrs(base, [action, channel, param])

    ev_s  = EVENT_NAMES[ev] if ev < len(EVENT_NAMES) else str(ev)
    ch_s  = f"channel {channel}" if channel else "no channel"
    print(f"Input {inp+1} / {ev_s}: action={ACTIONS.get(action)} {ch_s} param={param}")


def do_debounce_list(mb: Modbus, _args):
    """List debounce times for all inputs."""
    regs = mb.read_hr(HR_DEBOUNCE_BASE, INPUT_MAX)
    print(f"{'Input':>5}  {'Debounce ms':>12}")
    print('─' * 22)
    for i, ms in enumerate(regs):
        print(f"{i+1:>5}  {ms:>12}")


def do_debounce_set(mb: Modbus, args):
    """Set debounce time for one input."""
    inp = args.input - 1   # → 0-based
    if not 0 <= inp < INPUT_MAX:
        sys.exit(f"Error: input must be 1–{INPUT_MAX}")
    ms = args.ms
    mb.write_hr(HR_DEBOUNCE_BASE + inp, ms)
    print(f"Input {inp+1}: debounce set to {ms} ms")


def _decode_temp(raw: int) -> float | None:
    """Decode a raw Modbus temperature register to °C, or None if no reading."""
    if raw == TEMP_NO_READING:
        return None
    # Signed 16-bit, units of 0.1°C
    signed = raw if raw < 0x8000 else raw - 0x10000
    return signed / 10.0


def do_temps(mb: Modbus, _args):
    """Read all temperature sensors (LM75 external + RP2350 chip)."""
    regs = mb.read_ir(IR_TEMP_BASE, SENSOR_MAX)
    print(f"{'Sensor':>6}  {'Source':>20}  Temperature")
    print('─' * 44)
    for i, raw in enumerate(regs):
        if i == SENSOR_CHIP_TEMP_IDX:
            source = "RP2350 (chip)"
        else:
            source = f"LM75 @ 0x{0x48 + i:02X}"
        temp = _decode_temp(raw)
        temp_s = f"{temp:.1f} °C" if temp is not None else "— (no reading)"
        print(f"{i:>6}  {source:>20}  {temp_s}")


def do_ota_info(mb: Modbus, _args):
    """Show OTA / boot partition status."""
    regs     = mb.read_hr(HR_OTA_SLOT, 2)   # 501, 502
    slot     = regs[0]
    buy_pend = regs[1]
    st_regs  = mb.read_hr(HR_OTA_STATUS, 2)   # 508, 509
    status   = st_regs[0]
    wr_lo    = st_regs[1]
    slot_s   = {0: 'A (0)', 1: 'B (1)'}.get(slot, str(slot))
    print(f"Current slot   : {slot_s}")
    print(f"Buy pending    : {'YES — trial boot, awaiting ota_confirm()' if buy_pend else 'no'}")
    print(f"OTA status     : {OTA_STATUS_NAMES.get(status, str(status))}")
    if status in (2, 3):
        print(f"Bytes written  : {wr_lo} (low 16 bits)")


def do_ota_flash(mb: Modbus, args):
    """Write a firmware image to the other slot over Modbus."""
    import os

    path = args.image
    if not os.path.exists(path):
        sys.exit(f"Error: file not found: {path}")

    with open(path, 'rb') as f:
        image = bytearray(f.read())
    if len(image) % 2:
        image += b'\xff'
    size = len(image)
    print(f"Image: {path}  ({size} bytes = {size / 1024:.1f} KB)")

    # Refuse if already active or erasing
    status = mb.read_hr(HR_OTA_STATUS, 1)[0]
    if status in (1, 2):
        sys.exit(f"Error: OTA busy (status={OTA_STATUS_NAMES.get(status)}). "
                 f"Send abort (cmd=3) first or wait for completion.")

    # Show target slot
    cur = mb.read_hr(HR_OTA_SLOT, 1)[0]
    other = 1 - cur if cur in (0, 1) else '?'
    print(f"Current slot: {cur}  →  writing to slot: {other}")

    # Set size and send BEGIN (deferred erase)
    mb.write_hr(HR_OTA_SIZE_LO, size & 0xFFFF)
    mb.write_hr(HR_OTA_SIZE_HI, (size >> 16) & 0xFFFF)
    mb.write_hr(HR_OTA_CMD, OTA_CMD_BEGIN)

    # Poll until ACTIVE — MCU is busy erasing flash, timeouts are expected
    print("Erasing...", end='', flush=True)
    deadline = time.monotonic() + 30.0
    while True:
        time.sleep(0.3)
        if time.monotonic() > deadline:
            sys.exit("\nError: erase timeout (30 s)")
        try:
            status = mb.read_hr(HR_OTA_STATUS, 1)[0]
        except ModbusError:
            print('.', end='', flush=True)
            continue
        if status == 2:
            print(" done.")
            break
        if status == 4:
            sys.exit("\nError: begin_update failed (flash error — see device log)")

    # Stream data
    CHUNK = HR_OTA_DATA_REGS * 2   # 240 bytes per FC16 transaction
    sent  = 0
    t0    = time.monotonic()
    while sent < size:
        chunk = image[sent : sent + CHUNK]
        regs  = [(chunk[i] << 8) | chunk[i + 1] for i in range(0, len(chunk), 2)]
        mb.write_hrs(HR_OTA_DATA, regs)
        sent += len(chunk)
        pct     = min(sent, size) / size * 100.0
        elapsed = time.monotonic() - t0 or 0.001
        rate    = sent / elapsed
        filled  = int(30 * pct / 100)
        bar     = '=' * filled + '-' * (30 - filled)
        print(f"\r[{bar}] {pct:5.1f}%  {rate / 1024:5.1f} KB/s ", end='', flush=True)
    print()

    # Finish (flush last partial page)
    mb.write_hr(HR_OTA_CMD, OTA_CMD_FINISH)
    deadline = time.monotonic() + 5.0
    while True:
        time.sleep(0.2)
        status = mb.read_hr(HR_OTA_STATUS, 1)[0]
        if status == 3:
            break
        if status == 4:
            sys.exit("Error: finish failed (see device log)")
        if time.monotonic() > deadline:
            sys.exit("Error: finish timeout")

    elapsed = time.monotonic() - t0
    rate    = size / elapsed
    print(f"Done. {size} bytes written to slot {other} in {elapsed:.1f} s "
          f"({rate / 1024:.1f} KB/s).")

    if args.trial:
        print("Triggering trial boot (FLASH_UPDATE reboot)...")
        mb.write_hr(HR_TRIAL_BOOT, SAVE_MAGIC)
        if args.no_confirm:
            print("--no-confirm set: skipping confirmation. Board will roll back on next power-cycle.")
        else:
            _ota_wait_and_confirm(mb)


def _ota_wait_and_confirm(mb: Modbus) -> bool:
    """Wait for device to reboot after a trial trigger, then send OTA confirm.

    Polls for up to 14 s after a 1.5 s initial sleep (total ≤15.5 s, within
    the 16 s watchdog window).  Sends OTA_CMD_CONFIRM once the device is back
    and buy_pending=1.  Returns True on success.
    """
    REBOOT_GRACE  = 1.5   # seconds: let the board start rebooting
    POLL_TIMEOUT  = 14.0  # seconds: polling window after grace period
    POLL_INTERVAL = 0.5   # seconds between polls

    print("Waiting for device to reboot", end='', flush=True)
    time.sleep(REBOOT_GRACE)

    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        try:
            regs     = mb.read_hr(HR_OTA_SLOT, 2)  # 501=slot, 502=buy_pend
            slot     = regs[0]
            buy_pend = regs[1]
            slot_s   = {0: 'A', 1: 'B'}.get(slot, str(slot))
            print(f"\nDevice back on slot {slot_s}.")
            if not buy_pend:
                print("Warning: device is up but buy_pending=0 — already confirmed or wrong slot.")
                return False
            print("Confirming firmware via Modbus...", end='', flush=True)
            mb.write_hr(HR_OTA_CMD, OTA_CMD_CONFIRM)
            buy_pend = mb.read_hr(HR_OTA_BUY_PEND, 1)[0]
            if buy_pend:
                print(" FAILED (buy_pending still set)")
                return False
            print(" confirmed.")
            return True
        except ModbusError:
            print('.', end='', flush=True)
            time.sleep(POLL_INTERVAL)

    print("\nError: device did not come back within timeout.")
    return False


def do_ota_trial(mb: Modbus, args):
    """Trigger a trial boot of the other slot (no flash write)."""
    status = mb.read_hr(HR_OTA_STATUS, 1)[0]
    if status == 2:
        sys.exit("Error: OTA write in progress — finish or abort first")
    slot  = mb.read_hr(HR_OTA_SLOT, 1)[0]
    other = 1 - slot if slot in (0, 1) else '?'
    print(f"Triggering trial boot: slot {slot} → slot {other}")
    mb.write_hr(HR_TRIAL_BOOT, SAVE_MAGIC)
    if args.no_confirm:
        print("--no-confirm set: skipping confirmation. Board will roll back on next power-cycle.")
    else:
        _ota_wait_and_confirm(mb)


def do_ota_abort(mb: Modbus, _args):
    """Abort an in-progress OTA update."""
    status = mb.read_hr(HR_OTA_STATUS, 1)[0]
    if status not in (1, 2):
        print(f"Nothing to abort (OTA status: {OTA_STATUS_NAMES.get(status, status)}).")
        return
    mb.write_hr(HR_OTA_CMD, OTA_CMD_ABORT)
    print("OTA aborted.")


def do_ota_confirm(mb: Modbus, _args):
    """Explicitly confirm the running trial firmware (buy the TBYB image)."""
    buy_pend = mb.read_hr(HR_OTA_BUY_PEND, 1)[0]
    if not buy_pend:
        print("Nothing to confirm (buy_pending=0).")
        return
    mb.write_hr(HR_OTA_CMD, OTA_CMD_CONFIRM)
    buy_pend = mb.read_hr(HR_OTA_BUY_PEND, 1)[0]
    if buy_pend:
        sys.exit("Error: confirm sent but buy_pending is still set.")
    print("Firmware confirmed.")


def do_reboot(mb: Modbus, _args):
    """Trigger a watchdog reboot of the device."""
    print("Rebooting device via watchdog...")
    mb.write_hr(HR_SYS_REBOOT, SAVE_MAGIC)
    print("Board is rebooting.")


# ── Home Assistant Modbus config generator ───────────────────────────────────

def _ha_slug(name: str) -> str:
    """Turn a display name into a safe unique_id suffix."""
    return name.lower().replace(' ', '_').replace('-', '_')


def do_ha_config(mb: Modbus, args):
    """Generate a Home Assistant modbus: YAML block from the live device config."""
    import datetime

    # Read device identity
    info_regs = mb.read_hr(HR_DEVICE_VER, 10)
    git_hash  = (info_regs[HR_BUILD_HASH_HI] << 16) | info_regs[HR_BUILD_HASH_LO]
    fw_ver    = info_regs[HR_FW_VERSION]

    # Read channel configs
    cfgs = read_all_channel_cfgs(mb)

    slave  = args.addr
    port   = args.port
    baud   = args.baud
    parity = {'E': 'even', 'O': 'odd', 'N': 'none'}.get(args.parity.upper(), 'even')
    name   = getattr(args, 'ha_name', 'switcher2')

    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    lights   = []
    blinds   = []
    sensors  = []
    bin_sens = []
    numbers  = []

    for ch in range(CHANNEL_MAX):
        s    = ch * CH_CFG_SIZE
        regs = cfgs[s : s + CH_CFG_SIZE]
        typ  = regs[0]
        label = f"ch{ch}"   # default; HA user can rename in UI

        if typ == 1:  # light
            lights.append((ch, label))
        elif typ == 2:  # blind
            blinds.append((ch, label))

    # ── Build output ──────────────────────────────────────────────────────────
    o = []
    def w(line=''):
        o.append(line)

    w(f"# switcher2 Home Assistant Modbus configuration")
    w(f"# Generated: {now}  firmware: {fw_ver >> 8}.{fw_ver & 0xFF}  git: {git_hash:08x}")
    w(f"# Add to configuration.yaml or include via !include")
    w()
    w(f"modbus:")
    w(f"  - name: {name}")
    w(f"    type: serial")
    w(f"    port: {port}")
    w(f"    baudrate: {baud}")
    w(f"    parity: {parity}")
    w(f"    bytesize: {args.bytesize}")
    w(f"    stopbits: {args.stopbits}")
    w(f"    method: rtu")

    # ── Lights → switches ────────────────────────────────────────────────────
    if lights:
        w()
        w(f"    # ── Lights (channels: {', '.join(str(c) for c, _ in lights)}) ─────────────────────")
        w(f"    switches:")
        for ch, label in lights:
            uid = f"sw2_{name}_{label}"
            w(f"      - name: \"{name} {label}\"")
            w(f"        unique_id: {uid}")
            w(f"        device_address: {slave}")
            w(f"        write_type: holding")
            w(f"        address: {HR_CH_CMD_BASE + ch}   # HR {HR_CH_CMD_BASE + ch}")
            w(f"        command_on: 1")
            w(f"        command_off: 0")
            w(f"        verify:")
            w(f"          input_type: input")
            w(f"          address: {IR_STATUS_BASE + ch}   # IR {IR_STATUS_BASE + ch}")
            w(f"          state_on: 1")
            w(f"          state_off: 0")

    # ── Blinds → numbers + motion sensors ────────────────────────────────────
    if blinds:
        w()
        w(f"    # ── Blind position controls (write 0–10000) ─────────────────────────────")
        w(f"    numbers:")
        for ch, label in blinds:
            uid = f"sw2_{name}_{label}_set"
            w(f"      - name: \"{name} {label} set position\"")
            w(f"        unique_id: {uid}")
            w(f"        device_address: {slave}")
            w(f"        address: {HR_CH_CMD_BASE + ch}   # HR {HR_CH_CMD_BASE + ch}")
            w(f"        data_type: uint16")
            w(f"        min_value: 0")
            w(f"        max_value: 10000")
            w(f"        step: 100")

    # ── Sensors: blind positions + temperatures ───────────────────────────────
    # All sensors in a single block (YAML keys must be unique per mapping level)
    w()
    w(f"    sensors:")
    if blinds:
        w(f"      # Blind position sensors (0 = closed, 10000 = open).")
        w(f"      # See template cover example at the bottom of this file.")
        for ch, label in blinds:
            uid = f"sw2_{name}_{label}_pos"
            w(f"      - name: \"{name} {label} position\"")
            w(f"        unique_id: {uid}")
            w(f"        device_address: {slave}")
            w(f"        input_type: input")
            w(f"        address: {IR_STATUS_BASE + ch}   # IR {IR_STATUS_BASE + ch}")
            w(f"        data_type: uint16")
            w(f"        scale: 0.01")
            w(f"        precision: 0")
            w(f"        unit_of_measurement: \"%\"")
        if blinds:
            w()
        w(f"      # Blind motion state: 0=idle 1=opening 2=closing")
        for ch, label in blinds:
            uid = f"sw2_{name}_{label}_motion"
            w(f"      - name: \"{name} {label} motion\"")
            w(f"        unique_id: {uid}")
            w(f"        device_address: {slave}")
            w(f"        input_type: input")
            w(f"        address: {IR_MOTION_BASE + ch}   # IR {IR_MOTION_BASE + ch}")
            w(f"        data_type: uint16")
        w()
    w(f"      # Temperature sensors. 0x8000 (32768) = no reading yet.")
    sensor_labels = [f"LM75 0x{0x48 + i:02X}" for i in range(SENSOR_MAX - 1)] + ["RP2350 chip"]
    for i, slabel in enumerate(sensor_labels):
        uid = f"sw2_{name}_temp_{i}"
        w(f"      - name: \"{name} temperature {slabel}\"")
        w(f"        unique_id: {uid}")
        w(f"        device_address: {slave}")
        w(f"        input_type: input")
        w(f"        address: {IR_TEMP_BASE + i}   # IR {IR_TEMP_BASE + i}")
        w(f"        data_type: int16")
        w(f"        scale: 0.1")
        w(f"        precision: 1")
        w(f"        unit_of_measurement: \"°C\"")
        w(f"        device_class: temperature")
        w(f"        state_class: measurement")

    # ── Binary sensors: physical inputs ──────────────────────────────────────
    # (Single binary_sensors block — motion is a 3-state sensor above)
    w()
    w(f"    binary_sensors:")
    w(f"      # Physical inputs (1 = pressed/active)")
    for i in range(INPUT_MAX):
        uid = f"sw2_{name}_input_{i + 1}"
        w(f"      - name: \"{name} input {i + 1}\"")
        w(f"        unique_id: {uid}")
        w(f"        device_address: {slave}")
        w(f"        input_type: discrete_input")
        w(f"        address: {DI_INPUT_BASE + i}   # DI {DI_INPUT_BASE + i}")

    # ── Template cover example for blinds ─────────────────────────────────────
    if blinds:
        w()
        w(f"# ── Template covers for blinds ──────────────────────────────────────────────")
        w(f"# Add to configuration.yaml (or a separate included file).")
        w(f"# Requires the sensor/number entities above to be set up first.")
        w(f"template:")
        w(f"  - cover:")
        for ch, label in blinds:
            uid = f"sw2_{name}_{label}_cover"
            pos_sensor = f"sensor.{_ha_slug(f'{name} {label} position')}"
            set_number = f"number.{_ha_slug(f'{name} {label} set position')}"
            w(f"      - name: \"{name} {label}\"")
            w(f"        unique_id: {uid}")
            w(f"        device_class: blind")
            w(f"        position_template: \"{{{{ states('{pos_sensor}') | int(0) }}}}\"")
            w(f"        open_cover:")
            w(f"          service: number.set_value")
            w(f"          target:")
            w(f"            entity_id: {set_number}")
            w(f"          data:")
            w(f"            value: 10000")
            w(f"        close_cover:")
            w(f"          service: number.set_value")
            w(f"          target:")
            w(f"            entity_id: {set_number}")
            w(f"          data:")
            w(f"            value: 0")
            w(f"        set_cover_position:")
            w(f"          service: number.set_value")
            w(f"          target:")
            w(f"            entity_id: {set_number}")
            w(f"          data:")
            w(f"            value: \"{{{{ (position * 100) | int }}}}\"")
            w(f"        stop_cover:")
            w(f"          service: modbus.write_register")
            w(f"          data:")
            w(f"            hub: {name}")
            w(f"            unit: {slave}")
            w(f"            address: {HR_CH_CMD_BASE + ch}")
            w(f"            value: 10001")
            w(f"        is_closed_template: \"{{{{ states('{pos_sensor}') | int(0) == 0 }}}}\"")

    print('\n'.join(o))

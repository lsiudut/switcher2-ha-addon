"""Small pymodbus RTU wrapper used by ha_bridge devices."""
import logging
import threading
import time

from pymodbus.client import ModbusSerialClient

import sw2lib

log = logging.getLogger(__name__)


class ModbusSerialHandle:
    """Shared RTU serial connection for one physical port."""

    def __init__(
        self,
        port: str,
        baud: int,
        parity: str = 'E',
        bytesize: int = 8,
        stopbits: int = 1,
        timeout: float = 0.2,
    ):
        self.port = port
        self.lock = threading.RLock()
        self._refcount = 0
        self._closed = False
        self._client = None
        self._settings = None
        self.ensure_settings(
            baud=baud,
            parity=parity,
            bytesize=bytesize,
            stopbits=stopbits,
            timeout=timeout,
        )

    @property
    def client(self):
        if self._client is None:
            raise sw2lib.ModbusError(f"Serial port {self.port} is closed")
        return self._client

    @property
    def timeout(self) -> float:
        if self._settings is None:
            return 0.0
        return self._settings[4]

    def ensure_settings(
        self,
        baud: int,
        parity: str = 'E',
        bytesize: int = 8,
        stopbits: int = 1,
        timeout: float = 0.2,
    ) -> None:
        settings = (baud, parity, bytesize, stopbits, timeout)
        with self.lock:
            if self._client is not None and self._settings == settings:
                return
            old = self._settings
            start = time.monotonic()
            if old is None:
                log.debug(
                    f"{self.port}: opening serial {baud} {bytesize}{parity}{stopbits} "
                    f"timeout={timeout}"
                )
            else:
                log.debug(
                    f"{self.port}: switching serial "
                    f"{old[0]} {old[2]}{old[1]}{old[3]} timeout={old[4]} -> "
                    f"{baud} {bytesize}{parity}{stopbits} timeout={timeout}"
                )
            if self._client is not None:
                self._client.close()
            self._client = ModbusSerialClient(
                port=self.port,
                framer='rtu',
                baudrate=baud,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
                timeout=timeout,
            )
            if not self._client.connect():
                self._client = None
                self._settings = None
                raise sw2lib.ModbusError(f"Cannot connect to {self.port}")
            self._settings = settings
            elapsed_ms = (time.monotonic() - start) * 1000.0
            log.debug(f"{self.port}: serial ready in {elapsed_ms:.1f} ms")

    def acquire(self) -> None:
        if self._closed:
            self._closed = False
        self._refcount += 1

    def release(self) -> None:
        if self._closed:
            return
        self._refcount -= 1
        if self._refcount <= 0:
            if self._client is not None:
                self._client.close()
                self._client = None
                self._settings = None
            self._closed = True


class ModbusBus:
    """Modbus RTU slave facade backed by a shared serial connection."""

    def __init__(
        self,
        port: str,
        baud: int,
        slave: int,
        parity: str = 'E',
        bytesize: int = 8,
        stopbits: int = 1,
        timeout: float = 0.2,
        handle: ModbusSerialHandle | None = None,
    ):
        self._slave = slave
        self._baud = baud
        self._parity = parity
        self._bytesize = bytesize
        self._stopbits = stopbits
        self._timeout = timeout
        self._handle = handle or ModbusSerialHandle(
            port=port,
            baud=baud,
            parity=parity,
            bytesize=bytesize,
            stopbits=stopbits,
            timeout=timeout,
        )
        self._handle.acquire()
        self._closed = False

    def _client(self):
        self._handle.ensure_settings(
            baud=self._baud,
            parity=self._parity,
            bytesize=self._bytesize,
            stopbits=self._stopbits,
            timeout=self._timeout,
        )
        return self._handle.client

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._handle.release()

    @staticmethod
    def _check_exception(response, func_code: int) -> None:
        is_err = (
            (hasattr(response, 'is_error') and response.is_error()) or
            (hasattr(response, 'isError') and response.isError())
        )
        if is_err:
            code = getattr(response, 'exception_code', 0)
            raise sw2lib.ModbusError(
                f"Exception FC=0x{func_code:02X} code={code} "
                f"({sw2lib.EXCEPTION_CODES.get(code, 'unknown')})"
            )

    @staticmethod
    def _call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            raise sw2lib.ModbusError(str(e)) from e

    def read_hr(self, addr: int, count: int) -> list[int]:
        resp = self._call(self._client().read_holding_registers,
                          address=addr, count=count, device_id=self._slave)
        self._check_exception(resp, 0x03)
        return list(resp.registers)

    def read_registers(self, address: int, count: int, functioncode: int = 3) -> list[int]:
        if functioncode == 3:
            return self.read_hr(address, count)
        if functioncode == 4:
            return self.read_ir(address, count)
        raise sw2lib.ModbusError(f"Unsupported read function code {functioncode}")

    def write_hr(self, addr: int, value: int) -> None:
        resp = self._call(self._client().write_register,
                          address=addr, value=value, device_id=self._slave)
        self._check_exception(resp, 0x06)

    def write_hrs(self, addr: int, values: list[int]) -> None:
        resp = self._call(self._client().write_registers,
                          address=addr, values=values, device_id=self._slave)
        self._check_exception(resp, 0x10)

    def write_registers(self, address: int, values) -> None:
        self.write_hrs(address, list(values))

    def read_di(self, addr: int, count: int) -> list[bool]:
        resp = self._call(self._client().read_discrete_inputs,
                          address=addr, count=count, device_id=self._slave)
        self._check_exception(resp, 0x02)
        return [bool(b) for b in resp.bits[:count]]

    def read_ir(self, addr: int, count: int) -> list[int]:
        resp = self._call(self._client().read_input_registers,
                          address=addr, count=count, device_id=self._slave)
        self._check_exception(resp, 0x04)
        return list(resp.registers)


class ModbusManager:
    """Owns shared RTU handles and lends configured bus facades per transaction."""

    def __init__(self):
        self._handles: dict[str, ModbusSerialHandle] = {}
        self._buses: dict[str, ModbusBus] = {}

    def add_device(self, device_id: str, serial: dict, cfg: dict) -> ModbusBus:
        port = serial.get('port', '/dev/ttyUSB0')
        baud = int(serial.get('baud', serial.get('baudrate', 19200)))
        parity = str(serial.get('parity', 'E'))
        bytesize = int(serial.get('bytesize', 8))
        stopbits = int(serial.get('stopbits', 1))
        timeout = float(serial.get('timeout', cfg.get('timeout', 0.2)))
        handle = self._handles.get(port)
        if handle is None:
            handle = ModbusSerialHandle(
                port=port,
                baud=baud,
                parity=parity,
                bytesize=bytesize,
                stopbits=stopbits,
                timeout=timeout,
            )
            self._handles[port] = handle
        bus = ModbusBus(
            port=port,
            baud=baud,
            slave=int(serial.get('slave_addr', serial.get('slave', 22))),
            parity=parity,
            bytesize=bytesize,
            stopbits=stopbits,
            timeout=timeout,
            handle=handle,
        )
        self._buses[device_id] = bus
        return bus

    def bus_for(self, device_id: str) -> ModbusBus:
        return self._buses[device_id]

    def borrow(self, device_id: str):
        bus = self.bus_for(device_id)
        return _BorrowedBus(bus)

    def close(self) -> None:
        for bus in list(self._buses.values()):
            try:
                bus.close()
            except Exception:
                pass
        self._buses.clear()


class _BorrowedBus:
    def __init__(self, bus: ModbusBus):
        self._bus = bus
        self._handle = bus._handle

    def __enter__(self) -> ModbusBus:
        self._handle.lock.acquire()
        return self._bus

    def __exit__(self, exc_type, exc, tb) -> None:
        self._handle.lock.release()

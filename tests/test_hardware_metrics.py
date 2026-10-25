import importlib.util
from pathlib import Path
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('hardware_metrics',Path(__file__).resolve().parents[1]/'deploy/host/hardware_metrics.py');hardware=importlib.util.module_from_spec(spec);spec.loader.exec_module(hardware)


class HardwareMetrics(unittest.TestCase):
    def test_cpu_gpu_power_and_storage_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for index,name,temp in [(1,'coretemp','55000'),(2,'amdgpu','33000'),(3,'nvme','32850')]:
                p=root/f'hwmon{index}';p.mkdir();(p/'name').write_text(name);(p/'temp1_input').write_text(temp)
                if name=='amdgpu':(p/'power1_average').write_text('1000000')
            lines='\n'.join(hardware.collect('ubuntu-pc',root))
            self.assertIn('newbiegrader_cpu_temperature_celsius{node="ubuntu-pc"} 55.0',lines)
            self.assertIn('newbiegrader_gpu_power_watts{node="ubuntu-pc"} 1.0',lines)
            self.assertIn('32.85',lines)

    def test_missing_or_invalid_sensors_are_unavailable_not_zero_temperature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'hwmon1';p.mkdir();(p/'name').write_text('coretemp');(p/'temp1_input').write_text('nan')
            lines=hardware.collect('node',root)
            self.assertEqual(lines,['newbiegrader_cpu_sensor_available{node="node"} 0'])

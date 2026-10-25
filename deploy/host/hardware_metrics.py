"""Read existing kernel sensors; no probing, package installation or device writes."""
import json
import math
from pathlib import Path


def collect(node, root=Path('/sys/class/hwmon')):
    lines = []
    cpu_values = []
    for folder in root.glob('hwmon*'):
        try:
            name = (folder/'name').read_text().strip()
        except OSError:
            continue
        if name not in ('coretemp', 'k10temp', 'amdgpu', 'nvme'):
            continue
        for path in folder.glob('temp*_input'):
            try:
                value = float(path.read_text())/1000
                if not math.isfinite(value) or not -50 <= value <= 200:
                    continue
                label_path = path.with_name(path.name.replace('_input', '_label'))
                label = label_path.read_text().strip()[:60] if label_path.exists() else path.name.split('_')[0]
                labels = '{node='+json.dumps(node)+',sensor='+json.dumps(label)+'}'
                if name in ('coretemp', 'k10temp'):
                    cpu_values.append(value)
                elif name == 'amdgpu':
                    lines.append('newbiegrader_gpu_temperature_celsius'+labels+' '+str(value))
                else:
                    lines.append('newbiegrader_ssd_temperature_celsius'+labels+' '+str(value))
            except (OSError, ValueError):
                continue
        if name == 'amdgpu':
            try:
                watts = float((folder/'power1_average').read_text())/1000000
                if math.isfinite(watts) and 0 <= watts <= 1000:
                    lines.append('newbiegrader_gpu_power_watts{node='+json.dumps(node)+'} '+str(watts))
            except (OSError, ValueError):
                pass
    if cpu_values:
        lines.append('newbiegrader_cpu_temperature_celsius{node='+json.dumps(node)+'} '+str(max(cpu_values)))
    lines.append('newbiegrader_cpu_sensor_available{node='+json.dumps(node)+'} '+str(int(bool(cpu_values))))
    return lines

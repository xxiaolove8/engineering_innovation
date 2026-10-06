"""Finite left-only bench measurements; no AUTO or Flash writes."""
import argparse
import csv
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import statistics
import time

from host.protocol import CarClient, SerialLink, SimLink


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', default='COM5')
    p.add_argument('--simulate', action='store_true')
    p.add_argument('--mode', choices=['pwm', 'speed'], required=True)
    p.add_argument('--values', required=True)
    p.add_argument('--duration', type=float, default=3.0)
    p.add_argument('--settle', type=float, default=0.8)
    for name in ('speed_kp', 'speed_ki', 'speed_kd', 'target_ticks', 'feedforward_pwm'):
        p.add_argument('--' + name.replace('_', '-'), type=float)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    values = [float(v) for v in a.values.split(',')]
    ceiling = 300 if a.mode == 'pwm' else 10
    if (not 0.8 <= a.duration <= 8 or not 0 <= a.settle < a.duration or
            not 1 <= len(values) <= 12 or len(values)*a.duration > 60 or
            any(not 0 < v <= ceiling for v in values) or
            (a.mode == 'pwm' and any(v != int(v) for v in values))):
        p.error('Finite tests only: PWM integer 1..300; speed >0..10; total drive <=60 s.')
    output = Path(a.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {'started': datetime.now().astimezone().isoformat(),
              'simulation': a.simulate, 'arguments': vars(a), 'exchanges': [],
              'samples': [], 'summaries': [], 'completed': False}
    client = None
    original = None
    changed = False
    failed = False
    def log(direction, line):
        record['exchanges'].append({'time': time.time(), 'direction': direction, 'line': line})
    def stop():
        try:
            client.stop()
            s = client.status()
            if s.state != 'IDLE' or s.motor_left or s.motor_right:
                raise RuntimeError('STOP verification failed: '+str(s))
            record['stopped_status'] = asdict(s)
        except BaseException:
            # An I/O timeout invalidates SerialLink.request(); still send STOP.
            serial_port = getattr(client.link, '_port', None)
            if serial_port is not None and serial_port.is_open:
                serial_port.write(b'STOP\n')
            raise
    try:
        client = CarClient(SimLink() if a.simulate else SerialLink(a.port), log)
        stop()
        hw = client.hardware()
        if not hw.ready:
            raise RuntimeError('Hardware not ready: '+str(hw))
        original = client.pid().values
        record['original_pid'] = original
        record['original_saved'] = client.pid_saved()
        for name in ('speed_kp', 'speed_ki', 'speed_kd', 'target_ticks', 'feedforward_pwm'):
            value = getattr(a, name)
            if value is not None:
                changed = True
                client.set_pid(name, value)
        record['test_pid'] = client.pid().values
        print('PID', json.dumps(record['test_pid']), flush=True)
        for index, demand in enumerate(values):
            client.debug()
            start = time.monotonic()
            zero_since = None
            while time.monotonic() - start < a.duration:
                tick = time.monotonic()
                if a.mode == 'pwm':
                    client.drive(int(demand), 0, 1500)
                else:
                    client.speed(demand, 0)
                time.sleep(0.035)
                ctrl = client.control()
                elapsed = time.monotonic()-start
                row = {'step': index, 'demand': demand, 'seconds': round(elapsed, 4), **asdict(ctrl)}
                record['samples'].append(row)
                if ctrl.right_pwm != 0 or ctrl.right_target != 0:
                    raise RuntimeError('Unexpected right motor command: '+str(ctrl))
                if not 0 <= ctrl.left_pwm <= 300 or ctrl.left_measured > 25:
                    raise RuntimeError('Left output/feedback outside bench limits: '+str(ctrl))
                if ctrl.left_pwm >= 140 and ctrl.left_measured <= 0:
                    if zero_since is None:
                        zero_since = elapsed
                    elif elapsed-zero_since >= 0.8:
                        raise RuntimeError('No left encoder feedback while powered; stopping.')
                else:
                    zero_since = None
                time.sleep(max(0, 0.18-(time.monotonic()-tick)))
            signed = client.status()
            record.setdefault('signed_status', []).append(asdict(signed))
            stop()
            steady = [s for s in record['samples'] if s['step'] == index and s['seconds'] >= a.settle]
            summary = {'step': index, 'demand': demand, 'samples': len(steady),
                       'mean_speed': round(statistics.mean(s['left_measured'] for s in steady), 4),
                       'std_speed': round(statistics.pstdev(s['left_measured'] for s in steady), 4),
                       'min_speed': min(s['left_measured'] for s in steady),
                       'max_speed': max(s['left_measured'] for s in steady),
                       'mean_pwm': round(statistics.mean(s['left_pwm'] for s in steady), 4),
                       'max_pwm': max(s['left_pwm'] for s in steady),
                       'signed_left_delta': signed.encoder_left_delta}
            record['summaries'].append(summary)
            print('STEP', json.dumps(summary), flush=True)
            output.with_suffix('.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            time.sleep(0.5)
        record['completed'] = True
    except BaseException as exc:
        failed = True
        record['error'] = repr(exc)
        raise
    finally:
        if client is not None:
            try:
                stop()
                if failed and changed and original is not None:
                    for name, value in original.items():
                        client.set_pid(name, value)
                    record['restored_pid'] = client.pid().values
                record['final_pid'] = client.pid().values
            except BaseException as exc:
                record['cleanup_error'] = repr(exc)
            finally:
                client.close()
        record['finished'] = datetime.now().astimezone().isoformat()
        output.with_suffix('.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        if record['samples']:
            with output.with_suffix('.csv').open('w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=record['samples'][0].keys())
                writer.writeheader()
                writer.writerows(record['samples'])
        print('LOG', str(output.with_suffix('.json')), flush=True)


if __name__ == '__main__':
    main()

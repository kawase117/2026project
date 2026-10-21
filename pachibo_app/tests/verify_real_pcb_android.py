"""Use an already running disposable emulator-5580, never a physical device."""
import json
import subprocess
import sys
import time
from pathlib import Path

root=Path(__file__).parents[1]
adb=str(Path.home()/'AppData/Local/Android/Sdk/platform-tools/adb.exe')
serial=sys.argv[2] if len(sys.argv)>2 else 'emulator-5580'
if serial not in ('emulator-5580','emulator-5582'):
    raise SystemExit('Only disposable test emulator serials are allowed')
prefix=[adb,'-s',serial]


def command(*args):
    return subprocess.check_output(prefix+list(args),encoding='utf-8',errors='replace')


for _ in range(60):
    try:
        if command('shell','getprop','sys.boot_completed').strip()=='1':
            break
    except subprocess.CalledProcessError:
        pass
    time.sleep(1)
else:
    raise SystemExit('Emulator boot did not finish; leave running and inspect it')
for apk in ('debug/app-debug.apk','androidTest/debug/app-debug-androidTest.apk'):
    print(command('install','-r',str(root/'android/app/build/outputs/apk'/apk)),flush=True)
command('push',sys.argv[1],'/data/local/tmp/verification-input.pcb')
command('shell','run-as','jp.local.pachiboledger','mkdir','-p','files')
if subprocess.run(prefix+['shell','run-as','jp.local.pachiboledger','ls','files/verification-input.pcb'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
    command('shell','run-as','jp.local.pachiboledger','chmod','600','files/verification-input.pcb')
command('shell','run-as','jp.local.pachiboledger','cp','/data/local/tmp/verification-input.pcb','files/verification-input.pcb')
result=command('shell','am','instrument','-w','-e','real_pcb','true','jp.local.pachiboledger.test/jp.local.pachiboledger.BackupVerification')
print(result,flush=True)
if 'REAL_PCB_PASS' not in result:
    raise SystemExit('Android real PCB verification failed')
for name in ('verification-real-complete.zip','verification-real-audit.json'):
    with (root/'output'/name).open('wb') as output:
        subprocess.run(prefix+['exec-out','run-as','jp.local.pachiboledger','cat','files/'+name],stdout=output,check=True)
print('Saved Android output and audit locally')

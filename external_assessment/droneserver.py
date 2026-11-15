"""Optional adapter: run in a DroneServer environment, not Kimura's core runtime."""
import argparse,asyncio,json,os,subprocess,tempfile,types
from pathlib import Path
from .core import build,verify

async def assess(source, disable_auth, transport="in-process"):
    import droneserver
    actual=Path(droneserver.__file__).resolve()
    if not actual.is_relative_to(source/'src'):
        raise RuntimeError('installed DroneServer does not match specified checkout')
    commit=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    if subprocess.check_output(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],text=True).strip():
        raise RuntimeError('target tracked files must be clean')
    import droneserver.tools
    from droneserver.app import mcp
    from droneserver.tools import managed_mission as mm
    from droneserver.missions.runner import MissionRunner
    from droneserver.missions.state import MissionRecord,Phase
    from droneserver.safety import middleware as mw
    from droneserver.safety.config import SafetySettings
    rows=[]
    # Isolate all settings from .env/host environment. Do not instantiate a vehicle.
    for key in list(os.environ):
        if key.startswith('SAFETY_'): del os.environ[key]
    with tempfile.TemporaryDirectory(prefix='kimura-external-') as tmp:
        settings=SafetySettings(_env_file=None,api_keys='operator:LOCAL-CONTROL:control,observer:LOCAL-READ:telemetry',
            unauthenticated_scope='reject',auth_enabled=not disable_auth,audit_log_path=str(Path(tmp)/'audit.jsonl'))
        old_settings,old_layer,old_runner=mw.get_safety_settings,mw.LAYER,mm.RUNNER
        try:
            mw.get_safety_settings=lambda:settings
            mw.LAYER=mw.SafetyLayer()
            runner=MissionRunner()
            runner.record=MissionRecord('local-assessment',phase=Phase.RUNNING.value)
            mm.RUNNER=runner
            if transport == 'http-sse':
                from .http_sse import observe
                rows = await observe(mcp, runner)
            else:
                for role,key in [('control','LOCAL-CONTROL'),('telemetry','LOCAL-READ')]:
                    runner._pause_requested=False
                    before=runner._pause_requested
                    ctx=types.SimpleNamespace(request_context=types.SimpleNamespace(request=types.SimpleNamespace(headers={'x-api-key':key})))
                    response=await mcp._tool_manager.call_tool('control_managed_mission',{'action':'pause'},context=ctx)
                    rows.append({'role':role,'before':before,'after':runner._pause_requested,
                                 'status':response.get('status','missing'),'rule':response.get('rule')})
        finally:
            mw.get_safety_settings, mw.LAYER, mm.RUNNER=old_settings,old_layer,old_runner
    evidence=build({'repository':'https://github.com/PeterJBurke/droneserver','commit':commit,
        'auth_enabled':not disable_auth,'adapter':'http-sse-loopback/1' if transport == 'http-sse' else 'registered-tool-in-process/1'},rows)
    if not verify(evidence): raise RuntimeError('invalid generated evidence')
    return evidence

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--target-checkout',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--disable-auth-control',action='store_true',help='Local fake-mission sensitivity control only')
    p.add_argument('--transport',choices=['in-process','http-sse'],default='in-process')
    a=p.parse_args()
    if a.output.exists(): raise SystemExit('output already exists; use a fresh path')
    evidence=asyncio.run(assess(a.target_checkout.resolve(),a.disable_auth_control,a.transport))
    with a.output.open('x') as f: json.dump(evidence,f,indent=2); f.write('\n')
    print(json.dumps({'verdict':evidence['verdict'],'output':str(a.output)}))
if __name__=='__main__': main()

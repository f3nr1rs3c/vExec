#!/usr/bin/env python3
"""
vexec.py - Remote command executor for vSphere VMs via VMware Tools (pyvmomi)

Usage example:
python3 vexec.py --host 10.5.2.111 --user administrator@tellynet.ad --password 'VC_PASSWORD' \
    --vm "Windows-Server01" --guest-user "Administrator" --guest-pass "WinPass123" \
    --cmd "C:\\Windows\\System32\\cmd.exe" --args "/c echo Hello from vCollector!" --timeout 30
"""

import argparse
import ssl
import sys
import time
import getpass
import logging
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("vexec")


def parse_args():
    p = argparse.ArgumentParser(description="vExec - Run remote commands in vSphere VMs via VMware Tools")
    p.add_argument("--host", required=True, help="vCenter or ESXi hostname/IP")
    p.add_argument("--user", required=True, help="vCenter/ESXi username (e.g. administrator@vsphere.local)")
    p.add_argument("--password", help="vCenter/ESXi password (if omitted, will prompt)")
    p.add_argument("--no-ssl-verify", action="store_true", help="Disable SSL certificate verification (INSECURE)")
    p.add_argument("--vm", required=True, help="Target VM name (exact match)")
    p.add_argument("--guest-user", required=True, help="Username inside guest")
    p.add_argument("--guest-pass", help="Guest password (if omitted, will prompt)")
    p.add_argument("--cmd", required=True, help="Full path to program inside guest (e.g. C:\\Windows\\System32\\cmd.exe or /bin/sh)")
    p.add_argument("--args", default="", help="Arguments to program (string)")
    p.add_argument("--working-dir", default=None, help="Working directory inside guest (optional)")
    p.add_argument("--timeout", type=int, default=60, help="Timeout in seconds to wait for process completion (default: 60s)")
    p.add_argument("--poll-interval", type=float, default=1.0, help="Polling interval in seconds while waiting")
    return p.parse_args()


def connect_vsphere(host, user, pwd, no_ssl_verify=False):
    """
    Connect to vSphere and return service instance (si).
    """
    context = None
    if no_ssl_verify:
        try:
            context = ssl._create_unverified_context()
        except Exception:
            context = None

    try:
        si = SmartConnect(host=host, user=user, pwd=pwd, sslContext=context)
        logger.info("Connected to vSphere host %s", host)
        return si
    except Exception as e:
        logger.error("Failed to connect to vSphere host %s: %s", host, str(e))
        raise


def find_vm_by_name(si, vm_name):
    """
    Find a VM by name using ContainerView (works in vCenter and standalone ESXi).
    Returns vim.VirtualMachine or None.
    """
    content = si.RetrieveContent()
    obj_view = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
    try:
        for vm in obj_view.view:
            if vm.name == vm_name:
                logger.info("Found VM: %s (mo_ref: %s)", vm_name, vm._GetMoId())
                return vm
    finally:
        obj_view.Destroy()
    logger.error("VM named '%s' not found", vm_name)
    return None


def start_program_in_guest(si, vm, guest_user, guest_pass, program_path, args="", working_dir=None):
    """
    Start a program in the guest via GuestOperationsManager.processManager.
    Returns the started process PID (int).
    """
    content = si.RetrieveContent()
    gom = content.guestOperationsManager
    auth = vim.vm.guest.NamePasswordAuthentication(username=guest_user, password=guest_pass)
    pm = gom.processManager

    spec = vim.vm.guest.ProcessManager.ProgramSpec(programPath=program_path, arguments=args)
    if working_dir:
        spec.workingDirectory = working_dir

    try:
        pid = pm.StartProgramInGuest(vm=vm, auth=auth, spec=spec)
        logger.info("Started program in guest: %s %s -> pid=%s", program_path, args, pid)
        return pid, auth, pm
    except vim.fault.InvalidGuestLogin as e:
        logger.error("Invalid guest credentials: %s", e)
        raise
    except vmodl.MethodFault as mf:
        logger.error("Error starting program in guest: %s", mf)
        raise
    except Exception as e:
        logger.error("Unexpected error starting program in guest: %s", e)
        raise


def wait_for_process(pm, vm, auth, pid, timeout=60, poll_interval=1.0):
    """
    Poll ListProcessesInGuest until the process ends or timeout occurs.
    Returns exitCode (int) or None if no exit code available.
    """
    end_time = time.time() + timeout
    while time.time() <= end_time:
        try:
            proc_list = pm.ListProcessesInGuest(vm=vm, auth=auth, pids=[pid])
        except vmodl.MethodFault as mf:
            logger.error("Error listing guest processes: %s", mf)
            raise
        except Exception as e:
            logger.error("Unexpected error listing processes: %s", e)
            raise

        if not proc_list:
            # If the list is empty, process may have disappeared. Treat as finished with unknown exit.
            logger.warning("Process list call returned empty for pid %s; process may have exited.", pid)
            return None

        proc = proc_list[0]
        # GuestProcessInfo fields: pid, name, owner, exitCode, endTime etc.
        if hasattr(proc, "exitCode") and proc.exitCode is not None:
            logger.info("Process pid=%s finished with exitCode=%s", pid, proc.exitCode)
            return proc.exitCode
        # Not finished yet
        logger.debug("Process pid=%s still running. sleeping %s sec", pid, poll_interval)
        time.sleep(poll_interval)

    logger.warning("Timeout reached waiting for pid %s", pid)
    # After timeout, try one last time to obtain exitCode
    try:
        proc_list = pm.ListProcessesInGuest(vm=vm, auth=auth, pids=[pid])
        if proc_list and hasattr(proc_list[0], "exitCode"):
            return proc_list[0].exitCode
    except Exception:
        pass
    return None


def main():
    args = parse_args()

    if not args.password:
        args.password = getpass.getpass(prompt="vSphere password: ")

    if not args.guest_pass:
        args.guest_pass = getpass.getpass(prompt="Guest password: ")

    si = None
    try:
        si = connect_vsphere(args.host, args.user, args.password, no_ssl_verify=args.no_ssl_verify)
        vm = find_vm_by_name(si, args.vm)
        if vm is None:
            logger.error("Exiting because VM not found.")
            sys.exit(2)

        # Ensure VMware Tools are running / ready
        tools_status = getattr(vm.guest, "toolsRunningStatus", None)
        tools_version_status = getattr(vm.guest, "toolsVersionStatus", None)
        if tools_status != "guestToolsRunning":
            logger.warning("VMware Tools not in running state (toolsRunningStatus=%s, toolsVersionStatus=%s). "
                           "Guest operations may fail.", tools_status, tools_version_status)

        pid, auth, pm = start_program_in_guest(
            si=si,
            vm=vm,
            guest_user=args.guest_user,
            guest_pass=args.guest_pass,
            program_path=args.cmd,
            args=args.args,
            working_dir=args.working_dir,
        )

        # If StartProgramInGuest returns None or 0/invalid, still try to poll (some providers/versions behave differently)
        if pid is None:
            logger.warning("StartProgramInGuest returned None. Attempting to list processes to find likely PID.")
        else:
            logger.info("Monitoring process pid=%s for up to %s seconds", pid, args.timeout)

        exit_code = wait_for_process(pm=pm, vm=vm, auth=auth, pid=pid, timeout=args.timeout, poll_interval=args.poll_interval)
        if exit_code is None:
            logger.info("Process exit code unknown or process did not finish within timeout.")
            # Return non-zero to indicate unknown/timeout
            sys.exit(3)
        else:
            logger.info("Process completed with exit code: %s", exit_code)
            # exit with same code when possible (but keep in mind some exit codes are >255)
            try:
                sys.exit(int(exit_code) & 0xFF)
            except Exception:
                sys.exit(0)

    except Exception as e:
        logger.exception("Fatal error: %s", e)
        sys.exit(1)
    finally:
        if si:
            try:
                Disconnect(si)
                logger.info("Disconnected from vSphere.")
            except Exception:
                pass


if __name__ == "__main__":
    main()

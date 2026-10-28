#!/usr/bin/env python3
"""從固定來源快照更新產品白名單，三方合併本 checkout 的既有調整。"""

import argparse
from io import BytesIO
from pathlib import Path
import subprocess
import tarfile
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-repo', type=Path, required=True)
parser.add_argument('--previous', required=True)
parser.add_argument('--source', required=True)
parser.add_argument('--frontend-patch', type=Path, help='重套已核准的競賽版前端文字差異；已套用時不重複修改')
parser.add_argument('--apply', action='store_true', help='預設只列候選；加此參數才寫入')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
whitelist = ('backend', 'frontend', 'local_ai', 'ops/docker', 'ops/search', 'ops/icons', 'ops/tests', 'compose.test.yaml', 'ops/podcast/provider.py', 'ops/podcast/transcribe.py', 'ops/podcast/transcribe_media.py', 'ops/podcast/align.py', 'ops/podcast/stt-requirements.txt')

with tempfile.TemporaryDirectory(prefix='studydy-sync-') as temporary:
    temporary = Path(temporary)
    snapshots = []
    for label, revision in (('previous', args.previous), ('source', args.source)):
        destination = temporary / label
        destination.mkdir()
        archive = subprocess.check_output(['git', '-C', str(args.source_repo), 'archive', revision, '--', *whitelist])
        with tarfile.open(fileobj=BytesIO(archive)) as source:
            source.extractall(destination, filter='data')
        snapshots.append(destination)
    previous, source = snapshots
    paths = sorted({p.relative_to(snapshot) for snapshot in snapshots for p in snapshot.rglob('*') if p.is_file()})
    updates = []
    conflicts = []
    for name in paths:
        base, upstream, current = previous / name, source / name, root / name
        old = base.read_bytes() if base.is_file() else None
        new = upstream.read_bytes() if upstream.is_file() else None
        local = current.read_bytes() if current.is_file() else None
        if new == old or local == new:
            continue
        if local == old:
            updates.append((name, new, upstream.stat().st_mode if new is not None else None))
        elif local is None and old is not None:
            # 本 checkout 已不使用的來源檔案維持未選取狀態。
            continue
        elif None in (old, new, local) or any(b'\0' in value for value in (old, new, local)):
            conflicts.append(str(name))
        else:
            merged = subprocess.run(['git', 'merge-file', '-p', '-L', 'checkout', '-L', 'previous', '-L', 'source',
                                     str(current), str(base), str(upstream)], capture_output=True)
            if merged.returncode:
                conflicts.append(str(name))
            else:
                updates.append((name, merged.stdout, current.stat().st_mode))
    for name in conflicts:
        print(f'CONFLICT {name}')
    if conflicts:
        raise SystemExit('來源與 checkout 同時變更；尚未寫入。先核對衝突檔案後再同步。')
    if args.frontend_patch:
        patch = args.frontend_patch.resolve()
        entries = subprocess.check_output(['git', 'apply', '--numstat', '-z', str(patch)]).decode().split('\0')
        patch_paths = sorted({Path(entry.split('\t', 2)[2]) for entry in entries if entry})
        if any(name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0] != 'frontend' for name in patch_paths):
            raise SystemExit('前端差異只能包含 frontend/ 下的檔案；尚未寫入。')
        candidate = temporary / 'candidate'
        candidate.mkdir()
        planned = {name: (contents, mode) for name, contents, mode in updates}
        for name in patch_paths:
            current = root / name
            contents, mode = planned.get(name, (current.read_bytes() if current.is_file() else None,
                                                current.stat().st_mode if current.is_file() else 0o644))
            if contents is not None:
                target = candidate / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
                target.chmod(mode & 0o777)
        reverse = subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)], cwd=candidate, capture_output=True)
        if reverse.returncode == 0:
            print('FRONTEND_PATCH already applied')
        else:
            checked = subprocess.run(['git', 'apply', '--check', str(patch)], cwd=candidate, capture_output=True)
            if checked.returncode:
                raise SystemExit('FRONTEND_PATCH_CONFLICT：候選與已核准前端差異不符；尚未寫入，請交前端負責人核對。')
            subprocess.run(['git', 'apply', str(patch)], cwd=candidate, check=True)
            print('FRONTEND_PATCH reapplied')
        for name in patch_paths:
            target, current = candidate / name, root / name
            contents = target.read_bytes() if target.is_file() else None
            local = current.read_bytes() if current.is_file() else None
            if contents != local:
                planned[name] = (contents, target.stat().st_mode if contents is not None else None)
            else:
                planned.pop(name, None)
        updates = [(name, *value) for name, value in sorted(planned.items())]
    for name, contents, mode in updates:
        print(('DELETE ' if contents is None else 'UPDATE ') + str(name))
        if args.apply:
            target = root / name
            if contents is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
                target.chmod(mode & 0o777)
    print(f'{len(updates)} changes; ' + ('applied' if args.apply else 'preview only'))

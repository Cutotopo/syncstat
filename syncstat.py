#!/usr/bin/env python3

import hashlib
import os
import shutil
import sqlite3
import sys

HASH_BUF_SIZE=65536

filedir = "."
if not filedir.endswith('/'):
    filedir = f"{filedir}/"

def quickid(mtime, size):
    return (mtime, size)

def hashfile(path):
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        data = f.read(HASH_BUF_SIZE)
        while data:
            sha256.update(data)
            data = f.read(HASH_BUF_SIZE)
    return sha256.hexdigest()

def populate_db(source_directory, dbcon):
    dbc = []
    for cwd, directories, files in os.walk(source_directory):
        for file in files:
            # Ignore the db itself
            if file == '.syncstatdb':
                continue

            path = os.path.join(cwd, file)
            pathSv = os.path.relpath(path, source_directory)
            sha256 = hashfile(path)
            mtime = int(os.path.getmtime(path))
            size = os.path.getsize(path)
            dbc.append((pathSv, sha256, mtime, size))
            print(f"\rIndexing files... Found {len(dbc)} items.", end="")
    
    print(f"\rIndexing files... Done with {len(dbc)} items.")

    print("Copying data to database...", end="")
    cur = dbcon.cursor()
    cur.executemany("INSERT INTO Files VALUES (?, ?, ?, ?)", dbc)
    dbcon.commit()
    print(" Done.")

def full_sync(source_directory, destination_directory):
    for cwd, directories, files in os.walk(source_directory):
        for directory in directories:
            rel = os.path.relpath(os.path.join(cwd, directory), source_directory)
            targ = os.path.join(destination_directory, rel)
            os.makedirs(targ, exist_ok=True)
        for file in files:
            if file == '.syncstatdb':
                continue
            rel = os.path.relpath(os.path.join(cwd, file), source_directory)
            targ = os.path.join(destination_directory, rel)
            if not os.path.exists(targ):
                shutil.copy2(os.path.join(cwd, file), targ)

def partial_sync(source_directory, destination_directory, diff, dbcon):
    print("Processing sync and updating database...")
    cur = dbcon.cursor()
    if len(diff['added']):
        for file in diff['added']:
            print(f" --> Added '{file['path']}'.")
            source = os.path.join(source_directory, file['path'])
            target = os.path.join(destination_directory, file['path'])
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
            cur.execute("INSERT INTO Files VALUES (?, ?, ?, ?)", (file['path'], hashfile(source), int(os.path.getmtime(source)), os.path.getsize(source)))
    if len(diff['removed']):
        for file in diff['removed']:
            print(f" --> Removed '{file['path']}'.")
            try:
                os.remove(os.path.join(destination_directory, file['path']))
            except FileNotFoundError:
                print(f"[W] File '{file['path']}' does not exist. Ignoring and marking as synced.")
            cur.execute("DELETE FROM Files WHERE Path = ?", (file['path'],))
    if len(diff['changed']):
        for file in diff['changed']:
            print(f" --> Overwritten '{file['path']}'.")
            source = os.path.join(source_directory, file['path'])
            shutil.copy2(source, os.path.join(destination_directory, file['path']))
            cur.execute("UPDATE Files SET Hash = ?, Mtime = ?, Size = ? WHERE Path = ?", (hashfile(source), int(os.path.getmtime(source)), os.path.getsize(source), file['path']))
    if len(diff['renamed']):
        for file in diff['renamed']:
            print(f" --> Moved '{file['from']}' to '{file['to']}'.")
            target = os.path.join(destination_directory, file['to'])
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                os.rename(os.path.join(destination_directory, file['from']), target)
            except FileNotFoundError:
                print(f"[W] File '{file['from']}' does not exist. Ignoring and marking as renamed.")
            except FileExistsError:
                print(f"[W] Could not rename to '{file['to']}' because destination already exists. Ignoring and marking as renamed.")
            cur.execute("UPDATE Files SET Path = ? WHERE Path = ?", (file['to'], file['from']))
    dbcon.commit()
    print("Done syncing.")
    print("Looking for empty dirs...", end="")
    dcount = 0
    for cwd, directories, files in os.walk(destination_directory, topdown=False):
        for directory in directories:
            cpath = os.path.join(cwd, directory)
            if not os.listdir(cpath):
                os.rmdir(cpath)
                dcount += 1
                print(f"\rLooking for empty dirs... {dcount} removed.", end="")
    print(f"\rLooking for empty dirs... {dcount} removed.")

def find_hash(hash, dbcon):
    cur = dbcon.cursor()
    res = cur.execute("SELECT * FROM FILES WHERE Hash = ?", (hash,))
    dat = res.fetchall()
    if (len(dat) > 1): # More than one file with the same hash found. Do nothing. Better safe than sorry.
        return False
    elif (len(dat) == 0): # No results, nothing to compare with
        return False
    else: # Found the file we moved.
        return dat[0]

def find_differences(source_directory, dbcon):
    # Get data from DB
    cur = dbcon.cursor()
    res = cur.execute("SELECT * FROM Files")
    dbc = res.fetchall()
    dct = {}
    for file in dbc:
        dct[file[0]] = {
            'hash': file[1],
            'mtime': file[2],
            'size': file[3]
        }
    
    # Prepare diff dict
    dff = {
        'added': [],
        'removed': [],
        'changed': [],
        'renamed': []
    }

    for cwd, directories, files in os.walk(source_directory):
        for file in files:
            # Ignore the db itself
            if file == '.syncstatdb':
                continue

            path = os.path.join(cwd, file)
            pathSv = os.path.relpath(path, source_directory)
            if pathSv not in dct.keys():
                dftest = find_hash(hashfile(path), dbcon)
                if dftest:
                    dff['renamed'].append({
                        'from': dftest[0],
                        'to': pathSv
                    })

                    # File is handled, remove it from dict
                    dct.pop(dftest[0], None)
                else:
                    dff['added'].append({
                        'path': pathSv
                    })
            else:
                mtime = int(os.path.getmtime(path))
                size = os.path.getsize(path)

                # Check whether the file has changed, eventually append it to changelist
                if (quickid(mtime, size) != quickid(dct[pathSv]['mtime'], dct[pathSv]['size'])):
                    dff['changed'].append({
                        'path': pathSv
                    })
                
                # Changed or not, this file is handled, remove it from dict
                dct.pop(pathSv, None)
    
    # The only files that remain in the dict are the removed ones
    for path in dct.keys():
        dff['removed'].append({
            'path': path,
            'hash': dct[path]['hash'],
            'mtime': dct[path]['mtime'],
            'size': dct[path]['size']
        })
    
    return dff
            

if (len(sys.argv) != 3):
    print("[!] Subcommand and target required.")
    sys.exit(1)

target_dir = os.path.join(sys.argv[2])
target_db = os.path.join(target_dir, '.syncstatdb')

match sys.argv[1]:
    case 'init':
        print("[i] Warning. This will copy the entire directory over to the specified target and wipe its local database (if there is one).")
        t = input("[i] Please type 'yes' if you are sure about doing this, or anything else to cancel: ")
        if t != 'yes':
            sys.exit(3)

        con = sqlite3.connect(target_db)
        cur = con.cursor()
        print("Creating database schema...", end="")
        cur.executescript('''
        DROP TABLE IF EXISTS Files;

        CREATE TABLE IF NOT EXISTS "Files" (
            "Path"	TEXT,
            "Hash"	TEXT,
            "Mtime"	INTEGER,
            "Size"	INTEGER,
            PRIMARY KEY("Path")
        );
        ''')
        print(" Done.")

        populate_db(filedir, con)
        
        con.close()
        
        print("Cloning tree to target...", end="")
        full_sync(filedir, target_dir)
        print(" Done.")

        print("[i] All done.")
        sys.exit(0)
    case 'diff':
        if not os.path.exists(target_db):
            print("[!] Database not found in target. Please run 'syncstat init <target>'.")
            sys.exit(2)
        con = sqlite3.connect(target_db)

        print("Comparing tree with database. This may take a while.")

        dff = find_differences(filedir, con)
        if (len(dff['added'])):
            print("Added:")
            for file in dff['added']:
                print(f" - {file['path']}")
        if (len(dff['removed'])):
            print("Removed:")
            for file in dff['removed']:
                print(f" - {file['path']}")
        if (len(dff['changed'])):
            print("Changed:")
            for file in dff['changed']:
                print(f" - {file['path']}")
        if (len(dff['renamed'])):
            print("Moved:")
            for file in dff['renamed']:
                print(f" - {file['from']} -> {file['to']}")
        if len(dff['added']) == 0 and len(dff['changed']) == 0 and len(dff['removed']) == 0 and len(dff['renamed']) == 0:
            print(" - No changes were found in this tree when compared to the provided database.")

        con.close()
        sys.exit(0)
    case 'sync':
        if not os.path.exists(target_db):
            print("[!] Database not found in target. Please run 'syncstat init <target>'.")
            sys.exit(2)
        con = sqlite3.connect(target_db)

        print("Preparing to sync. This may take a while.")

        dff = find_differences(filedir, con)

        partial_sync(filedir, target_dir, dff, con)

        con.close()
        sys.exit(0)


print("[!] Invalid subcommand.")
sys.exit(1)

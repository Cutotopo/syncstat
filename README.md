# syncstat
The way to go about syncing your iPod over slow usb if you update your library somewhat frequently.

Note: your iPod must be running `rockbox`. The stock firmware is not supported and will likely never be. Use iTunes for that.

## What is this really?
Let's say you copied your library to your iPod (or any PMP really). All cool, you're vibing to music while going places now.<br>
But the next day, you are playing back one file on your PC and see some metadata field is incorrect.<br>
You fire up Picard and update it, you maybe sync it to your network storage of choice.<br>
But the iPod doesn't sync: remember, this is not iTunes. We are on our own here.<br>
So the next time you want to sync the iPod, you gotta remember "oh wait I also updated this file. need to copy over the new version on the iPod".

This effectively seeks to solve this problem:
 - Your file manager would probably try to diff the files before overwriting. We're probably all familiar with how slow the iPod's usb interface is, so sadly `diff` is not of much help here.
 - We can actually get around this by creating a small database on the iPod, hashing and caching information for all files when we copy them over there.
 - Our host computer can efficiently calculate if a file has changed or not, orders of magnitude faster than whatever our usb link is
 - So when we copy a file, we check the database for the file name, the size and the last time the contents have changed.
   - if we find the file in the database we skip it and we are happy
   - if we don't we overwrite it and update the database
 - The best part? We never read the files back from the iPod, just the small database, so it will be a lot faster in calculating changes. This also means that we won't run into any of the limitations the FAT32/HFS filesystems have!

## How do I install?
First of all, download the script to somewhere that is on your `PATH`.<br>
**I will use `/usr/local/bin` just as an example because you are going to find that on pretty much any modern-ish distro, but use whatever you prefer, preferably not system-wide if you aren't really sure about doing that.**<br>
**If you have it setup, something like `~/.local/bin` is so much better for this kind of stuff.**
```bash
curl https://raw.githubusercontent.com/Cutotopo/syncstat/refs/heads/main/syncstat.py -o syncstat.py
chmod +x syncstat.py
sudo mv syncstat.py /usr/local/bin/syncstat
```

## A database???
Yes. That would stay under `.syncstatdb` on your iPod's Music folder, and will be a sqlite db with a `Files` table.
For each file the script handles, we collect three main pieces of information:
 - sha256 hash
 - mtime
 - file size

When we start the diff process, the database gets read from the iPod and compared with whatever we have in our local directory.
We do a very lazy check (mtime and size) to determine if the file has changed in any way, then sync whatever is actually different without needing to overwrite anything else.
We store sha256sums anyway, so we can efficiently detect rewrites and just move the file as needed without copying it back.

## Downsides
You are effectively surrendering your ability to manage stuff as you want on the iPod. All of your library management should pass through here, **ideally**.
Usage of multiple machines to sync should not be a problem by itself, as long as you keep your stuff synced and you do that properly (i.e. with metadata).

## How do I use it?
Glad you asked. So, you first have to initialize the database on your iPod.
Delete everything from your iPod's Music folder (see FAQs below for more about this), then `cd` to wherever you keep your music collection and run
```bash
syncstat init /path/to/your/ipod/mount/Music
```
It will ask you if you are sure you want to copy your entire music collection to the iPod and index a new database.
That is fine: the only reason this warning exists is so the command doesn't get executed by mistake during angry arrow-up or ctrl-r spamming in the terminal.

So now you are perfectly synced. Congrats!

When you eventually get around to updating your library, just `cd` to your music collection and run
```bash
syncstat diff /path/to/your/ipod/mount/Music
```

This will be a summary of what will be done on your iPod. If you see nothing weird, go ahead with
```bash
syncstat sync /path/to/your/ipod/mount/Music
```
to go ahead and effectively start applying your changes!

## FAQ
 - Can I manage multiple iPods or PMPs with this?
   - Absolutely. every device has its own local database, and you can even sync different directories with them!
 - Do I need any special things installed via `pip`?
   - Nope. All python built-ins!
 - I just finished syncing my iPod with my PC. Do I really need to delete everything?
   - Let's say it would be ideal. It's mostly so you can be sure of what is on the iPod and what isn't, otherwise the script should just skip over existing files without overwriting them. It will take a while though, and if you want and you know what you are doing you can skip that process, just comment out the `full_sync` from the `init` handler in the script, `cd` to the source folder you sync your iPod from, `init` the database **and then put back the line where it was**. Just make sure that the directories are the same, else things could get kinda messed up when it syncs.
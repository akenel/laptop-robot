# Is anything using the camera?

```
sudo fuser -v /dev/video0
```

No output = nothing is using the camera right now.
Output = a list of programs (user, process ID, name) that have it open.

Without `sudo` it only sees your own programs and prints a wall of
"Permission denied" for the rest; `2>/dev/null` hides that noise:

```
fuser -v /dev/video0 2>/dev/null
```

Stronger proof than any software: cover the lens or unplug the webcam.

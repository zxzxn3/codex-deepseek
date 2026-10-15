# Bell sounds

- `prompt.oga`: prompt submitted.
- `complete.oga`: response finished or approval requested.

Replace either file with your own sound, keeping its filename. Installed hooks
play these paths directly, so no configuration change or reinstall is needed.
Missing sound files are silently skipped at playback time.
Use audio that `paplay` can decode; renaming a file does not convert its format.

## Default sound sources

Both files come from [sound-theme-freedesktop 0.8](https://people.freedesktop.org/~mccann/dist/sound-theme-freedesktop-0.8.tar.bz2).
`prompt.oga` was renamed from `message.oga`; the audio is unchanged.

| File | Credit and original source | License |
| --- | --- | --- |
| `prompt.oga` | Ivica Bukvic, [Borealis sound theme](http://gnome-look.org/content/show.php/%22Borealis%22+sound+theme?content=12584) | CC BY-SA (version unspecified in upstream credits) |
| `complete.oga` | Dr. Richard Boulanger et al., [Berklee collection](https://archive.org/details/Berklee44v11) | [CC BY 3.0 Unported](https://creativecommons.org/licenses/by/3.0/) |

These licenses apply to the bundled sounds, not the project's code.

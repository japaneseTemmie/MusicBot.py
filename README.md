# MusicBot.py
Feature-rich Discord music bot written in Python.

# Setup
First, go to discord.com/developers and set up a new application and a bot, then, invite the bot to your server.
While creating a bot, save the bot token as it will be required later on.

Download the source code and extract to a directory of your choice.
Open a terminal window in that directory to install dependencies. A *venv* is recommended to isolate dependencies.

# Required dependencies
- discord (For interacting with the API)
- yt_dlp (For fetching tracks from YouTube)
- PyNaCl (Additional voice support for discord.py)

Use `pip install <dependency>` to install the required packages.

Audio playback also requires ffmpeg to be installed on the host machine.
On Debian based Linux distributions, you can install ffmpeg by typing `sudo apt install ffmpeg`.
You can test if ffmpeg is installed by typing `ffmpeg` in a command line, a help message should appear if installed correctly.

On Windows, ffmpeg must be downloaded, extracted and added to the PATH environment variable.

After installing required dependencies, you can optionally open client.py in a text editor to configure the bot. Most options are already configured with default settings.

Create a file called "bot_token.txt" (case sensitive) and paste in your bot token at line 1 and nothing else.
Additionally, you can set REQUIRED_ROLE_NAME in client.py if you want to check for a specific role that the user must have before executing a command, default value is None, which means that
no checks will be made.

Example:
... Other client.py code

REQUIRED_ROLE_NAME: str = "DJ" # Will check for "DJ" role in the user's guild.

Then, to run the bot, type `python3 main.py`.
The bot should then initialize everything and go online, which is confirmed if you see "Logged in as <yourbotusername>".
The bot is now listening for commands.

NOTE: This Discord music bot is mostly just a fun project and does not work across multiple guilds (servers). The bot is meant to operate in a single guild.

# Usage and features
Once the bot is online, run >musichelp (Substitute ">" with your custom prefix if defined in client.py) to see all music features and usage help.
The bot also includes a small moderation class, its help menu can be shown with >modhelp.

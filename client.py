import discord
from discord.ext import commands
from botToken import get_token
import os
from sys import platform

""" Client properties 
to change the bot's status or its activity 
edit the appropriate variables"""

COMMAND_PREFIX: str = ">" # Command prefix used to invoke a command.
intents: discord.Intents = discord.Intents.all()
activity: discord.Activity = discord.Activity(
    name="lofi music",
    type=discord.ActivityType.listening,
    state="Chilling in a cozy house on a mountain",
) # Bot activity, remove "activity=activity" in the client variable declaration to remove the activity from the bot.
statuses: list[discord.Status, discord.Status, discord.Status] = [
    discord.Status.do_not_disturb, discord.Status.idle, discord.Status.online
]
IS_FFMPEG_INSTALLED: int = os.system("ffmpeg") # 0 yes 1 no
OS: str = platform
BOT_TOKEN_FILE_NAME: str = "bot_token.txt" # What filename the bot should look for in its directory for the bot token.
DIR: str = os.path.dirname(__file__)
LOG_FILENAME: str = "bot.log" # File where errors and warnings will be written to.
REQUIRED_ROLE_NAME: str | None = None # Used to check if a user has a specific role before allowing music commands execution. None or empty string means checks will be ignored.
YDL_OPTIONS: dict = {"format": "bestaudio", "noplaylist": True, "quiet": True}
PLAYLIST_FILENAME: str = "playlists.json"
token: str = get_token(BOT_TOKEN_FILE_NAME) # Actual token string, the function will return a string from the file BOT_TOKEN_FILE_NAME in DIR.

client: commands.Bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, activity=activity)
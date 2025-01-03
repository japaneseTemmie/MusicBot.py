import discord
from discord.interactions import Interaction
from discord.ext import commands
from moderation import Moderation
from music import Mixer
from botutils import BotUtils
from client import client, activity, statuses, COMMAND_PREFIX, LOG_FILENAME, token, DIR, REQUIRED_ROLE_NAME, BOT_TOKEN_FILE_NAME, IS_FFMPEG_INSTALLED, OS
import os
import asyncio
import random
import logging
from time import sleep

def check_for_log() -> None:
    if os.path.exists(LOG_FILENAME):
        os.remove(LOG_FILENAME)

def check_for_errors() -> None:
    if not BOT_TOKEN_FILE_NAME:
        print("No bot token filename specified in client.py. Program cannot continue with execution.")
        logging.error("No bot token filename specified in client.py.")
        sleep(3)
        exit(1)

    if not REQUIRED_ROLE_NAME:
        print(f"Required role property not set in {DIR + "/client.py"}. Bot will ignore any user role check for music commands.")
        sleep(3)

    if IS_FFMPEG_INSTALLED == 1: # ffmpeg -h exits with code 1 (either it's not installed or something went wrong with ffmpeg)
        print("FFmpeg seems to not be installed on this machine. Program cannot continue with execution.")
        logging.error("FFmpeg seems to not be installed on this machine. Is the package installed? Is it in the PATH variable?")
        sleep(3)
        exit(1)

    if not LOG_FILENAME:
        print(f"No log filename specified in {DIR + "/client.py"}. Using a generic log filename.")
        sleep(3)

    if not COMMAND_PREFIX:
        print("No command prefix found. Program cannot continue with execution.")
        logging.error(f"No command prefix found in {DIR + "/client.py"}.")
        sleep(3)
        exit(1)

@client.event
async def on_ready() -> None:
    print(f"OS: {OS}")
    print(f"PATH: {DIR}")

    print("Checking for old log file..")
    
    check_for_log()

    print("Setting up log file..")

    logging.basicConfig(
        filename=LOG_FILENAME if LOG_FILENAME else "bot-log.log",
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%d/%m/%Y, %H:%M:%S'
    )
    logging.warning("Log Begin.")

    check_for_errors()

    print(f"Logged in as {client.user}")
    
    await client.tree.sync() # Sync application commands

    if activity and statuses:
        await client.change_presence(activity=activity, status=random.choice(statuses))

@client.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.errors.MissingRequiredArgument) or isinstance(error, commands.errors.BadArgument):
        await ctx.send(f"Missing required parameter(s) for this command. See {COMMAND_PREFIX}musichelp or {COMMAND_PREFIX}modhelp for help.")
    elif isinstance(error, commands.errors.CommandOnCooldown):
        await ctx.send("Command is on cooldown.")
    elif isinstance(error, commands.errors.CommandNotFound):
        await ctx.send(f"Command failed to execute. Err: NotFound.\nCommand prefix is \"**{COMMAND_PREFIX}**\"Help commands:\n{COMMAND_PREFIX}musichelp\n{COMMAND_PREFIX}modhelp")
    elif isinstance(error, commands.errors.BotMissingPermissions):
        await ctx.send("I'm not allowed to do that!")
    elif isinstance(error, commands.errors.MissingPermissions):
        await ctx.send("You cannot use that command because you lack permissions to do so.")

""" Add the classes to the bot """

async def main():
    try:
        await client.add_cog(Mixer(client))
        await client.add_cog(Moderation(client))
        await client.add_cog(BotUtils(client))
    except commands.CommandError:
        print(f"Unknown or bad class passed to client.add_cog() in main(); Is the class inheriting from commands.Cog?")
        logging.error(f"Unknown or bad class passed to client.add_cog() in main(); Is the class inheriting from commands.Cog?")
        
        exit(1)

    try:
        await client.start(token)
    except TypeError:
        print(f"Unknown or bad argument passed to client.start() ; {token}")
        logging.error(f"Unknown or bad argument passed to client.start() in main() func ; {token}")
        
        exit(1)
    except Exception as e:
        print(f"Unknown error in while running client.start(); {e}")
        logging.error(f"Unknown error in main() func while running client.start(); {e}")
        
        exit(1)

asyncio.run(main())
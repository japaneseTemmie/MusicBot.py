import discord
from discord import app_commands
from discord.ext import commands
from discord.interactions import Interaction
from client import client, activity, statuses, COMMAND_PREFIX
from datetime import datetime
import random
from os import system

class BotUtils(commands.Cog):
    def __init__(self, client) -> None:
        self.client: commands.Bot = client
    
    @app_commands.command(name="ping", description="Get bot latency (in ms).")
    async def ping(self, interaction: Interaction) -> None:
        await interaction.response.send_message(f"Pong!\nLatency; {round(self.client.latency * 1000, 1)}ms")

    @app_commands.command(name="help", description="Outputs a help message.")
    async def show_help(self, interaction: Interaction) -> None:
        await interaction.response.send_message(f"Command prefix is \"**{COMMAND_PREFIX}**\"\nTo run a command, type:\n**{COMMAND_PREFIX}**<command>.\n\n**{COMMAND_PREFIX}**musichelp and **{COMMAND_PREFIX}**modhelp contain help for all features.")
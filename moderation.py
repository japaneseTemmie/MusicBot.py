import discord
from discord.ext import commands
from discord.interactions import Interaction
from discord import app_commands
import random
import datetime
import logging

class Moderation(commands.Cog):
    def __init__(self, client) -> None:
        self.client = client
    
    @commands.command()
    async def modhelp(self, ctx: commands.Context) -> None:
        embed = discord.Embed(
            colour=discord.Colour.random(seed=random.randint(1, 1000)),
            title="Moderation Help",
            timestamp=datetime.datetime.now()
        )

        embed.add_field(name=f"/purge", value=f"Deletes a selected amount of messages in the current channel or in a custom one\n\n**Parameters** (Optional)\n**Channel ID** (The channel's **ID**, default (empty) is the channel from where the user ran the command.)\nOptions: ID\n**Limit** (Max. amount of messages that can be deleted, defaults to 100)\n**Reason** (Reason for messages deletion)\n\nREQUIRES: Manage messages\nExample usage:\n/purge limit:50")
        embed.add_field(name=f"/ban", value=f"Bans a member from the server.\nParameters;\nuser: **Member ID**\nREQUIRES: Ban members\nExample usage:\n/ban <member_id> <reason>", inline=False)
        embed.add_field(name=f"/kick", value=f"Kicks a member from the guild.\nParameters;\nuser: **Member ID**\nREQUIRES: Kick members\nExample usage:\n/kick <member_id> <reason>", inline=False)

        await ctx.send(embed=embed)

    @app_commands.command(name="purge", description="Purges messages in a text channel.")
    @app_commands.describe(
        channel_id="The ID of the channel, leave empty for current channel.",
        limit="The maximum amount of messages that can be deleted. Defaults to 100.",
        reason="Reason for messages deletion."
    )
    @app_commands.default_permissions(manage_messages=True)
    async def purge(self, interaction: Interaction, channel_id: int=0, limit: int=100, reason: str="None") -> None:
        try:
            if channel_id == 0:
                channel_id = interaction.channel.id
            else:
                channel_id = int(channel_id)

        except Exception as e:
            await interaction.response.defer(thinking=True)
            await interaction.followup.send("Error while fetching channel.")
            logging.error(f"An error occured while fetching channel in function purge(); {e}")
            return

        try:
            channel: discord.TextChannel = self.client.get_channel(channel_id)
       
            await channel.purge(limit=limit, reason=reason)
            await interaction.response.defer(thinking=True)
            await interaction.followup.send(f"Purged channel **{channel.name} ({channel.id})** with message limit **{limit}** (Reason: **{reason}**).")
            
            if channel.id != interaction.channel.id:
                await channel.send(f"Purge request by **{interaction.user.name}** from channel **{interaction.channel.name}**. (Reason: **{reason}**)")
        except Exception as e:
            await interaction.response.defer(thinking=True)
            await interaction.followup.send("Failed to purge channel.")
            logging.error(f"An error occured while purging channel in function purge(); {e}")
            return
        except discord.Forbidden:
            await interaction.response.defer(thinking=True)
            await interaction.followup.send("I do not have permission to purge the channel!")
            return

    async def get_member_(self, ctx: commands.Context, user: str | int) -> discord.Member:
        try:
            member = ctx.guild.get_member(int(user))
        except ValueError:
            member = None
        
        if member is None:
            member = discord.utils.get(ctx.guild.members, name=user)
            if member is None:
                return None
        
        return member

    @app_commands.command(name="ban", description="Bans a user from the guild.")
    @app_commands.describe(
        user="The ID of the member.",
        reason="Ban reason."
    )
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: Interaction, user: int, reason: str) -> None:
        await interaction.response.defer(thinking=True)
        member = await self.get_member_(interaction, user)

        if member is None:
            await interaction.followup.send(f"Could not find user {user}.")
            return
        
        if member.id == interaction.user.id:
            await interaction.followup.send("You can't ban yourself!")
            return
            
        try:
            await member.ban(reason=reason)
            await interaction.followup.send(f"User **{user}** has been banned from the guild! (Reason: **{reason}**)")
        except discord.Forbidden:
            await interaction.followup.send("I do not have permission to ban this user.")
            return
        except Exception as e:
            await interaction.followup.send("An error occured while searching for user.")
            logging.error(f"An error occured while searching for user in function ban(); {e}")
            return

    @app_commands.command(name="kick", description="Kicks a user from the guild.")
    @app_commands.describe(
        user="The user to kick",
        reason="Kick reason"
    )
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: Interaction, user: int, reason: str) -> None:
        interaction.response.defer(thinking=True)
        
        member = await self.get_member_(ctx=interaction, user=user)

        if member is None:
            await interaction.followup.send(f"Could not find user **{user}**.")
            return
        
        if member.id == interaction.user.id:
            await interaction.followup.send("You can't kick yourself!")
            return

        try:
            await member.kick(reason=reason)
            await interaction.followup.send(f"User **{user}** has been kicked from the guild! (Reason: **{reason}**)")
        
        except discord.Forbidden:
            await interaction.followup.send("I do not have permission to kick this user.")
            return
        except Exception as e:
            await interaction.followup.send("An error occured while searching for the user.")
            logging.error(f"An error occured while searching user in function kick(); {e}")
            return
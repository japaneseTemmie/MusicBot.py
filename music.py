import discord
import discord.context_managers
from discord.interactions import Interaction
from discord.ext import commands
from client import client, activity, statuses, COMMAND_PREFIX, REQUIRED_ROLE_NAME, YDL_OPTIONS, PLAYLIST_FILENAME
from datetime import datetime
import asyncio
from yt_dlp import YoutubeDL
import time
import random
import re
import json
import os
import logging
import traceback

""" Generic Functions used for multiple purposes """

""" Formats seconds into MM:SS """
def format_time(seconds: int) -> str:
    minutes = seconds // 60
    remaining_seconds = seconds % 60

    return f"{minutes}:{remaining_seconds:02d}"
""" Formats MM:SS into SS """
def get_seconds(minutes: str) -> int:   
    minutes_split = minutes.split(":")
    seconds = int(minutes_split[0]) * 60 + int(minutes_split[1])
    
    return seconds

class Mixer(commands.Cog):
    """ Class containing commands for the music bot """
    
    def __init__(self, client) -> None:
        self.client: commands.Bot = client
        self.is_playing: bool = False
        self.is_modifying_queue: bool = False
        self.is_modifying_playlist: bool = False
        self.voice_client: discord.VoiceChannel = None
        self.current_track: str = None
        self.start_time: int = 0
        self.track_duration: int = 0
        self.last_elapsed_time: int = 0
        self.is_looping: bool = False
        self.is_random: bool = False
        self.track_to_loop: tuple = None
        self.webpage: str = None
        self.queue: list[tuple[str, str, int, str, str]] = []
        self.queue_history: list[tuple[str]] = []
        self.queue_to_loop: list[tuple[str, str, int, str, str]] = []
        self.data: dict = {}
        self.source: str = None
        self.after: bool = True # Variable to stop the bot from skipping tracks infinitely until the queue ends.
        self.is_looping_queue: bool = False
        self.file_lock: asyncio.Lock = asyncio.Lock() # Used to keep only 1 write request to playlists.json instead of multiple at the same time.
    
    """ Define helper functions """

    def get_query_type(self, query: str) -> str: # Returns "std_query" if the query pattern does not match a youtube url's
        youtube_url_pattern = re.compile(r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch|playlist\?v|list=|embed/|v/|.+\?v=)?([^&=%\?]{11})') # YouTube url pattern
        
        if youtube_url_pattern.match(query):
            return "url"
        return "std_query"

    def get_tracks(self, queue: list) -> str: # Joins all tracks in a single string from queue.
        tracks = []

        try:
            for (url, title, duration, thumbnail_url, webpage) in queue:
                title = title.strip()
                tracks.append(title)
        except ValueError: # Switch to playlist parsing
            for (title, url) in queue:
                title = title.strip()
                tracks.append(title)

        queue_str = ", ".join(tracks)

        if len(queue_str) > 1024:
            queue_str = queue_str[:1009] + "**[+ More]**"

        return queue_str
    
    def get_single_track_queue(self, queue: list) -> str:
        queue_str = ", ".join(queue)

        if len(queue_str) > 1024:
            queue_str = queue_str[:1009] + "**[+ More]**"

        return queue_str
    
    def shuffle_queue(self, queue: list) -> list:
        random.shuffle(queue)

        return queue

    """ Removes duplicates from a queue by creating a set and a new list
    and only appending items not in seen to it. """

    def remove_duplicates(self, queue: list[tuple[str, str, int, str, str]]) -> list:
        seen = set()
        unique = []
        for track in queue:
            title = track[1]
            
            if title not in seen:
                seen.add(title)
                unique.append(track)

        return unique

    async def check_for_role(self, ctx: commands.Context, required_role: str | None) -> bool:
        if required_role is None:
            return None

        # Check if role exists
        try:
            role = discord.utils.get(ctx.guild.roles, name=REQUIRED_ROLE_NAME)
        except Exception as e:
            logging.error(f"An error occured in function check_for_role(); {e}\n{traceback.format_exc()}")
        if role is None:
            logging.warning(f"Ignoring non existent role \"{REQUIRED_ROLE_NAME}\" in function check_for_role().")

            return None
        
        if role in ctx.author.roles:
            return True
        
        return False

    async def reposition_track(self, ctx: commands.Context, queue: list, track: str, position: int) -> None:
        """ Function to reposition a track from origin index to a new user-specified index. """
        
        embed = discord.Embed(
            title="Playlist Update",
            colour=discord.Colour.random(seed=random.randint(1, 1000)),
            timestamp=datetime.now()
        )

        found = False
        is_playlist = False
        try:
            for index, (url, title, duration, thumbnail_url, webpage) in enumerate(queue):
                if track.lower().replace(" ", "") in title.lower().replace(" ", ""):
                    if index == position:
                        await ctx.send("Cannot reposition a track to the same index.")
                        return
                    
                    track_info = queue.pop(index)
                    queue.insert(position, track_info)
                    
                    if track_info in self.queue_to_loop:
                        self.queue_to_loop.remove(track_info)
                        self.queue_to_loop.insert(position, track_info)
                    found = True
                    break
        except ValueError:
            is_playlist = True
            for index, (title, url) in enumerate(queue):
                if track.lower().replace(" ", "") in title.lower().replace(" ", ""):
                    if index == position:
                        await ctx.send("Cannot reposition a track to the same index.")
                        return
                    
                    track_info = queue.pop(index)
                    queue.insert(position, track_info)

                    found = True
                    break
        
        old_track_index = index + 1
        new_track_index = position + 1

        embed.add_field(name="Repositioned Track", value=track_info[1], inline=False) if not is_playlist else embed.add_field(
            name="Repositioned track", value=track_info[0], inline=False
        )
        embed.add_field(name="Old index", value=old_track_index, inline=True)
        embed.add_field(name="New index", value=new_track_index, inline=True)
        try:
            embed.add_field(name="New playlist", value=self.get_tracks(queue), inline=False)
        except ValueError:
            embed.add_field(name="New playlist", value=self.get_playlist_tracks(queue), inline=False)
        
        if found:
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"Track **{track}** not found in queue.")

    async def remove_track(self, ctx: commands.Context, queue: list[tuple[str, str]] | list[tuple[str, str, int, str, str]], *track_names: str) -> None:
        """ Function to remove a set of tracks from self.queue """
        
        removed_tracks = []
        tracks_not_found = []
        try:
            for track_name in track_names:
                found = False
                for i, (url, title, duration, thumbnail_url, webpage) in enumerate(queue):
                    if track_name.lower().replace(" ", "") in title.lower().replace(" ", ""):
                        removed_track = queue.pop(i)
                        removed_tracks.append(removed_track[1])

                        if removed_track in self.queue_to_loop:
                            self.queue_to_loop.remove(removed_track) # Also remove the same track from the loop queue.
                        found = True
                        break

                if not found:
                    if track_name not in tracks_not_found:
                        tracks_not_found.append(track_name)
        except ValueError:
            for track_name in track_names:
                found = False
                for i, (title, url) in enumerate(queue):
                    if track_name.lower().replace(" ", "") in title.lower().replace(" ", ""):
                        removed_track = queue.pop(i)
                        removed_tracks.append(removed_track[0])

                        found = True
                        break
                
                if not found:
                    if track_name not in tracks_not_found:
                        tracks_not_found.append(track_name)

        embed = discord.Embed(
            colour=discord.Colour.random(seed=random.randint(1, 1000)),
            title="Queue update",
            timestamp=datetime.now()
        )
        if tracks_not_found:
            embed.add_field(name="Tracks not found", value=", ".join([track for track in tracks_not_found]))
        if removed_tracks:
            embed.add_field(name="Removed tracks", value=", ".join([track for track in removed_tracks]))

        embed.add_field(name="New queue", value=self.get_tracks(queue))
        
        await ctx.send(embed=embed)

    """ Function to reset the bot's state to its default __init__ state 
    Called in case of disconnects. """

    def reset(self) -> None:
        self.voice_client: discord.VoiceChannel = None
        self.current_track: str = None
        self.is_modifying_queue: bool = False
        self.is_modifying_playlist: bool = False
        self.start_time: int = 0 # The start time of each track.
        self.track_duration: int = 0
        self.last_elapsed_time: int = 0 # The time that has elapsed since the track's start time. Updated when paused, rewound or forwarded.
        self.is_looping: bool = False # Simple flag to keep track of the looping state.
        self.is_random: bool = False # Another flag to keep track of the "random" state.
        self.track_to_loop: tuple = None # Updated every time the bot plays a new track. 
        self.webpage: str = None # "webpage" refers to the actual youtube webpage url that the bot extracts the source audio from, used mainly for the yoink command.
        self.queue: list = []
        self.queue_history: list = [] # Queue history, all played tracks are appended here and can be accessed with the $history command.
        self.queue_to_loop: list = [] # List where tracks are saved to when queue loop is enabled. Copies self.queue.
        self.data: dict = {} # Data about the currently playing track.
        self.source: str = None # Audio source, which is obtained from the extracted URL.
        self.after: bool = True # Variable to keep "play_next()" from looping infinitely.
        self.is_looping_queue: bool = False

    """ Call yt_dlp's extract_info() function to get
    the source URL of the audio. """

    def fetch_track(self, ctx: commands.Context, query_type: str, query: str) -> dict | str:
        """ Fetches a dictionary containing information about the
        requested query. Returns "no_entry" if no results can be found, "invalid_query" if the query has an invalid structure. """
        
        with YoutubeDL(YDL_OPTIONS) as yt:
            if query_type == "std_query":
                info = yt.extract_info(f"ytsearch:{query}", download=False) # Extract with query
            elif query_type == "url":
                info = yt.extract_info(query, download=False) # Extract without query.
            else:
                return "invalid_query"

            if not info:
                return "no_entry"

            if info and "entries" in info:
                info = info["entries"][0]

            return info

    async def play_track(self, ctx: commands.Context, url: str, data: dict, seconds: int=0, mode: str="default"): # mode can be either "rewind" "seek" "forward" or "default"
        """ Plays the track by launching a FFmpeg process with the FFMPEG_OPTIONS_CUSTOM flags
        Also updates the data dictionary with new information. """
        
        self.last_elapsed_time = int(time.time() - self.start_time) # Update time so it shows correctly in nowplaying / duration
        
        """ FFMPEG_OPTIONS_CUSTOM is a dictionary containing all settings that will be passed to
        ffmpeg. """

        FFMPEG_OPTIONS_CUSTOM = {
            'before_options': f'-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', # reconnect avoids stopping track playback on disconnect.
            'options': f'-ss {seconds} -vn'
        } # -ss means seek to {position}

        try:
            source = await discord.FFmpegOpusAudio.from_probe(url, **FFMPEG_OPTIONS_CUSTOM) # URL is the audio source extracted by yt.extract_info() in fetch_track()
            
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused(): # ctx.voice_client is the same as self.voice_client
                self.after = False # Stops the bot from calling play_next() infinitely
                ctx.voice_client.stop()
            ctx.voice_client.play(source, after=lambda _:self.client.loop.create_task(self.play_next(ctx))) # Plays audio through FFmpeg

            """ Update time and track variables """

            self.start_time = time.time() - seconds # Set start time, needed to keep track of elapsed time.
            self.last_elapsed_time = seconds # Elapsed time since the start of the track. Can be any number between 0 and the track length

            """ Track information will be stored in the self.data dictionary """

            self.current_track = data["title"]
            self.track_duration = data["duration"]
            self.thumbnail_url = data["thumbnail_url"]
            self.webpage = data["webpage"]
            self.source = url

            if self.current_track is not None:
                if self.current_track not in self.queue_history:
                    self.queue_history.append(self.current_track)

            if mode == "default": # Check to make the "Now playing" message only appear when playing the track automatically or by selecting it, not when seeking into it.
                await self.nowplaying(ctx)
        except discord.ClientException as e:
            await ctx.send("Failed to create FFmpeg process.")
            logging.error(f"An error occured while starting ffmpeg process in function play_track(): {traceback.format_exc()}")
            return
        except discord.HTTPException:
            await ctx.send("A Network error occured.")
            logging.error(f"An HTTP error occured in play_track() func; {e}\n{traceback.format_exc()}")
            return
        except Exception as e:
            await ctx.send("An error occured while playing track.")
            logging.error(f"An error occured in function play_track(): {traceback.format_exc()}")
            return

    @commands.command(name="join", help="Requests the bot to join the user's channel.")
    async def join(self, ctx: commands.Context) -> None:
        """ Makes the bot join the voice channel that the user who sent the command is currently in.
        """
        
        """ This will check for the required role set in client.py to be in the roles of the user that sent the command. """

        meets_role_requirement: bool | None = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False: # None means no role found in guild/REQUIRED_ROLE_NAME, False means that the role exists, but the user doesn't have it.
            await ctx.send("You do not have the required role to use this command.")
            return

        voice_channel = client.get_channel(ctx.author.voice.channel.id) if ctx.author.voice else None

        if not voice_channel:
            await ctx.send("You're not connected to a voice channel!")
            return

        try:
            if ctx.voice_client:
                if ctx.voice_client.channel.id == voice_channel.id:
                    await ctx.send("I'm already connected to your channel!")
                    return
                    
                if ctx.voice_client.channel.id != voice_channel.id:
                    await ctx.send(f"I cannot join your channel because i'm already in **{ctx.voice_client.channel.name}**!")
                    return
            else:
                self.voice_client = await voice_channel.connect() # Connect to the channel
                self.reset() # Wipe config on join.

            await ctx.send(f"Connected to **{voice_channel.name}**!")
        except Exception as e:
            await ctx.send("An error occured while joining your channel.")
            logging.error(f"An error occured while joining a channel in function join(): {traceback.format_exc()}")
            return
    
    @commands.command(name="leave", help="Requests the bot to leave its current channel.")
    async def leave(self, ctx: commands.Context) -> None:
        """ Requests the bot to leave its voice channel. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return

        if ctx.voice_client and not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id: # Avoid users that are not in the bot's channel to execute commands.
            await ctx.send("Join my voice channel first.")
            return
        
        if ctx.voice_client.is_playing():
            self.after = False # Fix for bot skipping tracks on disconnect.
            ctx.voice_client.stop()
        await ctx.send(f"Disconnected from **{ctx.voice_client.channel.name}**.")
        await ctx.voice_client.disconnect()
        self.reset()

    @commands.command(name="stop", help="Stops the current track and resets the bot.")
    async def stop(self, ctx: commands.Context) -> None:
        """ Stops whatever track is currently playing and wipes config data. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return

        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.") # Added to avoid users from stopping track if they are not in the same channel.
            return

        if not ctx.voice_client.is_playing() or self.data["title"] and ctx.voice_client.is_paused():
            await ctx.send("I'm not playing anything!")
            return

        track_name = self.data["title"]
        self.reset()

        self.after = False
        ctx.voice_client.stop()

        await ctx.send(f"Stopped track **{track_name}** and reset bot state.")

    """ Adds a track to self.queue, other functions such as playlist_select()
    can also use this. """

    @commands.command(name="add", help="Add a track to the queue.")
    async def add(self, ctx: commands.Context, *queries: str) -> None:
        """ Adds a new track to the queue. 
        Extracts url and other information from the source URL and appends all
        the data to self.queue. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.voice_client:
            await self.join(ctx)
        
        if ctx.voice_client and not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return

        if len(self.queue) >= 100:
            await ctx.send("Queue limit of **100** tracks reached. Please remove a track to free a slot.")
            return

        if not self.is_modifying_queue:
            self.is_modifying_queue = True
        else:
            await ctx.send("The queue is currently being modified, please wait.")
            return

        if queries:
            added_tracks = []
            failed_tracks = []
            embed = discord.Embed(
                title="Queue update",
                colour=discord.Colour.random(seed=random.randint(1, 1000)),
                timestamp=datetime.now()
            )
            async with ctx.typing(): # Makes the bot send a "is typing" request to the channel so that it makes it look like it's working from the user's perspective
                for query in queries:
                    query_type = self.get_query_type(query) # Figure out the query type (std_query, url)
                    
                    try:
                        info = await asyncio.to_thread(self.fetch_track, ctx, query_type, query) # Use to_thread() to avoid blocking code.
                        
                        if info == "invalid_query":
                            failed_tracks.append((query, "Invalid query type"))
                            continue
                        elif info == "no_entry":
                            failed_tracks.append((query, "No entries found for this query"))
                            continue

                        """ Collect matching track's information, including the source audio
                        and append it to the queue. """

                        webpage = info["webpage_url"]
                        url = info["url"]
                        title = info["title"]
                        thumbnail_url = info.get("thumbnail")
                        duration = info.get("duration", 0)

                        """ Append data to their respective queues
                        which will later be accessed by play_track(). """

                        self.queue.append((url, title, duration, thumbnail_url, webpage))
                        if (url, title, duration, thumbnail_url, webpage) not in self.queue_to_loop:
                            self.queue_to_loop.append((url, title, duration, thumbnail_url, webpage))
                        added_tracks.append(title)

                    except Exception:
                        failed_tracks.append((query, "Unknown error"))
                        continue
                if added_tracks:
                    embed.add_field(name=f"Added tracks **({len(queries)})**", value=self.get_single_track_queue(added_tracks), inline=False)
                if failed_tracks:
                    embed.add_field(name="Tracks not added", value=f"\n".join(f"**{query}**, ({error})" for query, error in failed_tracks))
                if not added_tracks and not failed_tracks:
                    await ctx.send("No tracks were added.")
                    return

                await ctx.send(embed=embed)
            if not ctx.voice_client.is_playing():
                await self.play_next(ctx)
            self.is_modifying_queue = False
        else:
            await ctx.send("No queries were given. Command aborted.")
            self.is_modifying_queue = False
            return

    async def play_next(self, ctx: commands.Context) -> None:
        """ Plays the next track in the queue at index 0 or at different indices based
        on is_looping or is_random conditions. """

        if not self.after:
            self.after = True
            return
        
        """ Avoid leaving the bot alone when all users have left the channel
        So she doesn't stay alone :( """

        if len(ctx.voice_client.channel.members) == 1:
            await ctx.send(f"Disconnecting from voice channel **{ctx.voice_client.channel.name}**...\nReason: No users left in channel.")
            self.after = False
            await ctx.voice_client.disconnect()

            return

        """ self.track_to_loop will be assigned the current track's info
        every time this function is called, so when replaying it again and self.is_looping is enabled
        it can loop until it's disabled. """

        if self.is_looping and self.track_to_loop and not self.is_random:
            url, title, duration, thumbnail_url, webpage = self.track_to_loop
        
        if self.is_looping_queue and not self.queue and self.queue_to_loop:
            self.queue = self.queue_to_loop.copy() # Copy the saved queue to the main queue to loop it

        if self.queue or self.is_looping or self.is_looping_queue:
            
            if not self.is_looping:
                url, title, duration, thumbnail_url, webpage = self.queue.pop(0) if not self.is_random else self.queue.pop(self.queue.index(random.choice(self.queue))) # Get the current track from the queue list
                self.track_to_loop = (url, title, duration, thumbnail_url, webpage) # Set it to the track_to_loop variable, in case it's needed for looping

            try:
                self.data = {
                    "title": title,
                    "duration": duration,
                    "thumbnail_url": thumbnail_url,
                    "webpage": webpage
                }
                self.start_time = time.time()
                self.last_elapsed_time = 0

                await self.play_track(ctx, url=url, data=self.data, seconds=0, mode="default")

            except Exception as e:
                await ctx.send(f"Error while playing the next track.")
                logging.error(f"An error occured in function play_next(): {traceback.format_exc()}")
                return
        elif not ctx.voice_client.is_playing():
            if self.is_looping_queue and self.queue_to_loop:
                self.queue = self.queue_to_loop.copy()
                await self.play_next(ctx)
            else:
                await ctx.send("Queue is empty.")
                self.queue_to_loop.clear()
                self.is_looping_queue = False

    @commands.command(name="skip", help="Skips the current track.")
    async def skip(self, ctx: commands.Context) -> None:
        """ Function to skip the current track and play the next one at self.queue[0][0] """

        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if not len(self.queue) >= 1 and not len(self.queue_to_loop) >= 1:
            await ctx.send("There's no track to play next.")
            return
        
        if self.is_modifying_queue:
            await ctx.send("The queue is currently being modified, please wait.")
            return

        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            self.is_looping = False # Stop the bot from looping
            ctx.voice_client.stop() # By calling this without setting self.after to False we execute the "after" func passed in ctx.voice_client.play()

            await ctx.send(f"Skipped track **{self.current_track}**.")

    @commands.command(name="pause", help="Pauses the player.")
    async def pause(self, ctx: commands.Context) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if ctx.voice_client:
            if ctx.voice_client.is_playing():
                ctx.voice_client.pause()
                self.last_elapsed_time = int(time.time() - self.start_time) # Update elapsed time
            else:
                await ctx.send("I'm not playing anything!")
                return
        else:
            await ctx.send("I'm not in any voice channel!")
            return
        
    @commands.command(name="resume", help="Resumes the player.")
    async def resume(self, ctx: commands.Context) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
            
        if ctx.voice_client.is_paused():
            self.start_time = time.time() - self.last_elapsed_time
            ctx.voice_client.resume()
        else:
            await ctx.send("I'm not paused!")
            return

    @commands.command(name="seek", help="Seek into the current track by a specified amount of time.")
    async def seek(self, ctx: commands.Context, position: str) -> None:
        """ Function to seek into the currently playing track."""
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return

        if ctx.voice_client.is_playing():
            try:
                position_seconds = get_seconds(position) # Reformat time to SS rather than MM:SS
            except Exception:
                await ctx.send("Invalid time format; use **MM:SS**")
                return

            if position_seconds >= 0 and position_seconds <= self.data["duration"]:
                # Seek directly to the user-provided time
                await self.play_track(ctx, self.source, data=self.data, seconds=position_seconds, mode="seek") # mode=seek avoids the "now playing" message
                await ctx.send(f"Set track positon to **{position}** seconds.")
            else:
                await ctx.send(f"Invalid position. Type a query between **0:00** and **{format_time(self.data["duration"])}**")
                return
        else:
            await ctx.send("I'm not playing anything!")
            return

    @commands.command(name="rewind", help="Rewinds the track by a specified amount of time.")
    async def rewind(self, ctx: commands.Context, position: str) -> None:
        """ Rewinding can be achieved by getting the current track's position,
        subtracting it by the user-provided time, and seeking into the track using the -ss FFmpeg option. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return

        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if ctx.voice_client.is_playing():
            try:
                position_seconds = get_seconds(position)
            except Exception:
                await ctx.send("Invalid time format; use **MM:SS**")
                return
            
            if position_seconds > 0 and position_seconds <= self.data["duration"]:
                new_position = int(time.time() - self.start_time) - position_seconds
    
                await self.play_track(ctx, url=self.source, data=self.data, seconds=new_position, mode="rewind")
                await ctx.send(f"Rewound by {position} seconds. Now at {format_time(new_position)} seconds.")
            else:
                await ctx.send("Invalid rewind position.")
                return
        else:
            await ctx.send("I'm not playing anything!")
            return

    @commands.command(name="forward", help="Forwards the track by a specified amount of time.")
    async def forward(self, ctx: commands.Context, position: str) -> None:
        """ Forwarding can be achieved by getting the current track's position,
        adding the user-provided time, and seeking into the track using the -ss FFmpeg option. (essentially the same as $rewind but addition). """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return

        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if ctx.voice_client.is_playing():
            try:
                position_seconds = get_seconds(position)
            except Exception:
                await ctx.send("Invalid time format; use MM:SS")
                return
            
            if position_seconds > 0 and position_seconds <= self.data["duration"]:
                new_position = int(time.time() - self.start_time) + position_seconds
                
                await self.play_track(ctx, url=self.source, data=self.data, seconds=new_position, mode="forward")
                await ctx.send(f"Forwarded by {position} seconds. Now at {format_time(self.last_elapsed_time)} seconds.")
            else:
                await ctx.send("Invalid forward position.")
                return
        else:
            await ctx.send("I'm not playing anything!")
            return
   
    @commands.command(name="reposition", help="Repositions a track to a new index in the queue.")
    async def reposition(self, ctx: commands.Context, track: str, position: int) -> None:
        """ Repositions a track to a different index than its original.
        Requires track name and new index. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return

        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return

        if not self.queue:
            await ctx.send("Nothing is in the queue!")
            return

        if not self.is_modifying_queue:
            self.is_modifying_queue = True
        else:
            await ctx.send("The queue is currently being modified, please wait.")
            return

        try:
            position = int(position)
        except Exception:
            await ctx.send("Index is not a number.")
            self.is_modifying_queue = False
            return
        if position < 1 or position > len(self.queue):
            await ctx.send(f"Invalid position. Input a value between **1** and **{len(self.queue)}**.")
            return
        
        position -= 1
        
        """ Loop through the queue list, searching for the matching track names, if found
        pop it and reinsert the new tuple at the new index. (position) """
        
        try:
            await self.reposition_track(ctx, self.queue, track, position)
        except IndexError as e:
            await ctx.send("Error while parsing queue.")
            logging.error(f"An error occured while parsing queue in reposition() func: {traceback.format_exc()}")
            return
        except Exception as e:
            await ctx.send(f"An error occured while repositioning the track.")
            logging.error(f"An error occured in reposition() func: {traceback.format_exc()}")
            return
        finally:
            self.is_modifying_queue = False

    @commands.command(name="duration", help="Outputs the elapsed time and duration of the current track.")
    async def duration(self, ctx: commands.Context) -> None:
        """ Function to fetch the track duration and current elapsed time. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await ctx.send("I'm not playing anything!")
            return
        
        embed = discord.Embed(
            title="Playback info",
            colour=discord.Colour.random(seed=random.randint(1, 1000)),
            timestamp=datetime.now()
        )

        if not ctx.voice_client.is_paused():
            self.last_elapsed_time = int(time.time() - self.start_time) # Get track elapsed time.

        embed.add_field(name="Track duration", value=f"{format_time(self.track_duration)} Minutes", inline=True)
        embed.add_field(name="Elapsed time", value=f"{format_time(self.last_elapsed_time)} Minutes", inline=True) if not ctx.voice_client.is_paused() and ctx.voice_client.is_playing() else embed.add_field(name="Elapsed time", value=f"{format_time(self.last_elapsed_time)} Minutes", inline=True)

        await ctx.send(embed=embed)

    @commands.command(name="restart", help="Restarts the current track.")
    async def restart(self, ctx: commands.Context) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        """ Call play_track() with seconds 0
        effectively restarting the track. """

        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            self.start_time = time.time()
            self.last_elapsed_time = 0
            await self.play_track(ctx, url=self.source, data=self.data, seconds=0, mode="default")
        else:
            await ctx.send("I'm not playing anything!")
            return
        
    @commands.command(name="remove", help="Removes a track from the queue.")
    async def remove(self, ctx: commands.Context, *track_names: str) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if not self.queue:
            await ctx.send("Queue is empty, no tracks can be removed.")
            return

        if not self.is_modifying_queue:
            self.is_modifying_queue = True
        else:
            await ctx.send("The queue is currently being modified, please wait.")
            return

        try:
            await self.remove_track(ctx, self.queue, *track_names)
        except Exception as e:
            await ctx.send("An error occured while removing track from queue.")
            logging.error(f"An error occured while removing a track in remove() func: {traceback.format_exc()}")
            return
        finally:
            self.is_modifying_queue = False
        
    @commands.command(name="clear", help="Clears the current queue and resets most flags.")
    async def clear(self, ctx: commands.Context) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        self.is_modifying_queue = True

        """ Reset queues to their original defaults by emptying the lists. """

        old_queue = self.queue[:]
        old_queue_history = self.queue_history[:]
        old_is_looping_queue = self.is_looping_queue
        old_is_looping = self.is_looping
        old_is_random = self.is_random
        
        self.queue.clear()
        self.queue_history.clear()
        self.queue_to_loop.clear()
        self.is_looping_queue = False
        self.is_looping = False
        self.is_random = False

        embed = discord.Embed(
            title="State update",
            colour=discord.Colour.random(seed=random.randint(1, 1000)),
            timestamp=datetime.now()
        )

        embed.add_field(name="Values reset", value=f"Queue: **{len(self.queue)}** (previous: **{len(old_queue)}**)\nHistory: **{len(self.queue_history)}** (previous: **{len(old_queue_history)}**)\nQueue loop: **{self.is_looping_queue}** (previous: **{old_is_looping_queue}**)\nLoop: **{self.is_looping}** (previous: **{old_is_looping}**)\nRandom choice: **{self.is_random}** (previous: **{old_is_random}**)")
        await ctx.send(embed=embed)

        self.is_modifying_queue = False

    @commands.command(name="loop", help="Sets a flag to enable loop for the current track.")
    async def loop(self, ctx: commands.Context) -> None:
        """ Simply uses a flag to determine whether or not
        the bot's supposed to loop the current track. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return

        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if self.is_random:
            await ctx.send("Loop cannot be enabled if randomized track selection is enabled.")
            return

        if not ctx.voice_client.is_playing():
            await ctx.send("I'm not playing anything!")
            return

        if self.is_modifying_queue:
            await ctx.send("The queue is currently being modified, please wait.")
            return

        if not self.is_looping:
            self.is_looping = True
            await ctx.send("The player will now loop the current track.")
        else:
            self.is_looping = False
            await ctx.send("The player will no longer loop.")

    @commands.command(name="random", help="Sets a flag to select a random track every time one finishes.")
    async def random(self, ctx: commands.Context) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if self.is_looping:
            await ctx.send("Randomization cannot be enabled if loop is already enabled.")
            return
        
        if self.is_modifying_queue:
            await ctx.send("The queue is currently being modified, please wait.")
            return

        if not self.is_random:
            self.is_random = True
            await ctx.send("The player will now choose a random track each time the previous one finishes playing.")
        else:
            self.is_random = False
            await ctx.send("The player will not randomize track selection anymore.")

    @commands.command(name="loopqueue", help="Sets a flag to loop the queue after all tracks finish playing.")
    async def loopqueue(self, ctx: commands.Context) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if self.is_looping:
            await ctx.send("Queue looping cannot be enabled if loop is enabled.")
            return

        if not self.queue and not self.queue_to_loop:
            await ctx.send("Cannot enable queue loop because the queue is empty.")
            return

        if self.is_modifying_queue:
            await ctx.send("The queue is currently being modified, please wait.")
            return

        if not self.is_looping_queue:
            self.is_looping_queue = True
            if not self.queue_to_loop or self.queue_to_loop != self.queue:
                self.queue_to_loop = self.queue.copy()

            await ctx.send("The queue will now be looped.")
        else:
            self.is_looping_queue = False
            self.queue_to_loop.clear()
            await ctx.send("The queue will no longer be looped.")

    @commands.command(name="history", help="Outputs the previously played tracks.")
    async def history(self, ctx: commands.Context) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        if self.queue_history:
            embed = discord.Embed(
                title="Queue History",
                colour=discord.Colour.random(seed=random.randint(1, 1000)),
                timestamp=datetime.now()
            )

            embed.add_field(name="All previously played tracks", value=self.get_single_track_queue(self.queue_history), inline=False) # get_single_track_queue() returns a string with all the tracks in an array with a [(url, title, duration, thumbnail_url, webpage)] structure.

            await ctx.send(embed=embed)
        else:
            await ctx.send(f"No tracks have been played yet. Use **{COMMAND_PREFIX}add** to play one!")

    @commands.command(name="shuffle", help="Shuffles the tracks in the queue.")
    async def shuffle(self, ctx: commands.Context) -> None:
        """ Calls self.shuffle_queue() which returns a shuffled queue """

        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        embed = discord.Embed(
            title="Queue update",
            colour=discord.Colour.random(seed=random.randint(1, 1000)),
            timestamp=datetime.now()
        )

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return

        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if not self.queue:
            await ctx.send("Nothing is in the queue. The queue cannot be shuffled.")
            return
        
        if not self.is_modifying_queue:
            self.is_modifying_queue = True
        else:
            await ctx.send("The queue is currently being modified, please wait.")
            return

        try:
            old_queue = self.queue[:]
            self.queue = self.shuffle_queue(self.queue) # shuffle_queue() simply returns a new list after being shuffled by random.shuffle()
            self.queue_to_loop = self.queue.copy()

            embed.add_field(name="The queue has been shuffled", value="", inline=False)
            visual_queue = self.queue[:]
            
            for i, (url, title_new, duration, thumbnail_url, webpage) in enumerate(self.queue):
                old_url, old_title, old_duration, old_thumbnail, old_webpage = old_queue[i]
                if title_new != old_title:
                    visual_queue[i] = (url, f"**{title_new}**", duration, thumbnail_url, webpage)

            embed.add_field(name="New queue", value=", ".join(title_new for url, title_new, duration, thumbnail_url, webpage in visual_queue))
            embed.add_field(name="Old queue", value=self.get_tracks(old_queue))

            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Error while shuffling queue.")
            logging.error(f"An error occured in shuffle() func: {traceback.format_exc()}")
        finally:
            self.is_modifying_queue = False

    @commands.command(name="sort", help="Sorts the tracks in the queue alphabetically.")
    async def sort(self, ctx: commands.Context) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        embed = discord.Embed(
            title="Queue update",
            colour=discord.Colour.random(seed=random.randint(1, 1000)),
            timestamp=datetime.now()
        )
        
        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return

        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if not self.queue:
            await ctx.send("No tracks in queue to sort.")
            return
        
        if len(self.queue) <= 1:
            await ctx.send("Cannot sort queue;\nOnly 1 track available.")
            return

        if not self.is_modifying_queue:
            self.is_modifying_queue = True
        else:
            await ctx.send("The queue is currently being modified, please wait.")
            return

        previous = self.queue[:]
        self.queue = sorted(self.queue, key=lambda track: track[1]) # Sorts list alphabetically using the second item (title) of the tuple.
        self.queue_to_loop.copy()

        if previous != self.queue:
            embed.add_field(name="New queue", value=self.get_tracks(self.queue), inline=True)
            embed.add_field(name="Old queue", value=self.get_tracks(previous), inline=True)

            await ctx.send(embed=embed)

        self.is_modifying_queue = False

    @commands.command(name="list", help="Outputs the tracks in the queue.")
    async def list_tracks(self, ctx: commands.Context) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if not self.queue: # Ensure there's a queue
            await ctx.send("The queue is empty.")
            return
        
        try:
            embed = discord.Embed(
                title="Queue",
                colour=discord.Colour.random(seed=random.randint(1, 1000)),
                timestamp=datetime.now()
            )

            embed.add_field(name="**All tracks**", value="", inline=False)
            embed.add_field(name="", value=self.get_tracks(self.queue), inline=False)
        
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"An error occured.")
            logging.error(f"An error occured in list_tracks() func: {traceback.format_exc()}")
            return

    """ Gets track information and sends it to the user who sent the command """

    @commands.command(name="yoink", help="Fetches information on the current track and sends it to the user who sent the command.")
    async def yoink(self, ctx: commands.Context) -> None:
        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return

        if ctx.voice_client.is_playing():
            user = ctx.message.author
            
            embed = discord.Embed(
                title="Track info",
                colour=discord.Colour.random(seed=random.randint(1, 1000)),
                timestamp=datetime.now()
            )
            
            if self.data["webpage"] and self.data["title"]:
                embed.add_field(name="Name", value=self.data["title"], inline=False)
                embed.add_field(name="URL", value=self.data["webpage"], inline=False)
                embed.set_image(url=self.data["thumbnail_url"])
            
                try:
                    await user.send(embed=embed)
                except discord.Forbidden:
                    await ctx.send("I can't send a message to you!")
                    return
                except Exception as e:
                    await ctx.send("Failed to send message.")
                    logging.error(f"An error occured in yoink() func: {traceback.format_exc()}")
                    return
            else:
                await ctx.send("Failed to fetch track.")
        else:
            await ctx.send("I'm not playing anything!")

    """ Plays a track the queue and not from a search query / url """
        
    @commands.command(name="select", help="Selects a track from the queue and plays it.")
    async def select(self, ctx: commands.Context, track: str) -> None:
        """ Loops through the queue searching for the matching track name, and, if found
        extract its info from the queue index and call self.play_track(). """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return

        if ctx.voice_client and not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return

        if not track:
            await ctx.send("No track was given, command aborted.")
            return

        if not self.is_modifying_queue:
            self.is_modifying_queue = True
        else:
            await ctx.send("The queue is currently being modified, please wait.")
            return

        try:
            for i, (url, title, duration, thumbnail_url, webpage) in enumerate(self.queue):
                found = False
                if track.lower().replace(" ", "") in title.lower().replace(" ", ""):
                    self.data = {
                        "title": title,
                        "duration": duration,
                        "thumbnail_url": thumbnail_url,
                        "webpage": webpage
                    }
                    
                    self.track_to_loop = url, title, duration, thumbnail_url, webpage

                    await self.play_track(ctx, url=url, data=self.data, seconds=0, mode="default")
                    selected_track = self.queue.pop(i)

                    if selected_track in self.queue_to_loop:
                        self.queue_to_loop.remove(selected_track)
                    found = True
                    break
            if not found:
                await ctx.send("No matching track found.")

        except Exception as e:
            await ctx.send(f"An error occured while parsing queue.")
            logging.error(f"An error occured in select() func: {traceback.format_exc()}")
            return
        finally:
            self.is_modifying_queue = False

    @commands.command(name="removedupes", help="Removes any duplicates from the queue.")
    async def removedupes(self, ctx: commands.Context) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        if ctx.voice_client and not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if not self.queue:
            await ctx.send("No tracks are present in the queue.")
            return
        
        if not self.is_modifying_queue:
            self.is_modifying_queue = True
        else:
            await ctx.send("The queue is currently being modified, please wait.")
            return

        previous_queue = self.queue[:] # Keep a copy of the queue to compare it
        embed = discord.Embed(
            title="Queue update",
            colour=discord.Colour.random(seed=random.randint(1, 1000)),
            timestamp=datetime.now()
        )

        try:
            self.queue = self.remove_duplicates(self.queue)
            self.queue_to_loop = self.queue.copy()
        except Exception as e:
            await ctx.send("An error occured while removing duplicates.")
            logging.error(f"An error occured in removedupes() func: {traceback.format_exc()}")
            return
        finally:
            self.is_modifying_queue = False

        if previous_queue != self.queue:
            unique_tracks = []
            for track in previous_queue:
                if track not in self.queue:
                    unique_tracks.append(track)

            embed.add_field(name="Removed duplicates", value=self.get_tracks(unique_tracks), inline=True)
            embed.add_field(name="New queue", value=self.get_tracks(self.queue), inline=True)

            await ctx.send(embed=embed)
        else:
            await ctx.send("No duplicates found in queue.")

        self.is_modifying_queue = False

    @commands.command(name="playnow", help="Stops current track if playing and plays the given one.")
    async def play_now(self, ctx: commands.Context, query: str) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        if not ctx.voice_client:
            await self.join(ctx)

        if ctx.voice_client and not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if not query:
            await ctx.send("No query provided.")
            return

        async with ctx.typing():
            old_track = None
            if self.source and self.data["title"] and self.data["duration"] and self.data["thumbnail_url"] and self.data["webpage"]:
                old_track = self.source, self.data["title"], self.data["duration"], self.data["thumbnail_url"], self.data["webpage"]
            
            try:
                query_type = self.get_query_type(query)
                
                info = await asyncio.to_thread(self.fetch_track, ctx, query_type, query)

                if info == "no_entry":
                    await ctx.send(f"No entry found for query **{query}**.")
                    return
                elif info == "invalid_query":
                    await ctx.send(f"Invalid query type for query **{query}**. Only YouTube search queries and URLs are supported.")
                    return
                
                url, title, duration, thumbnail_url, webpage = info["url"], info["title"], info.get("duration", 0), info.get("thumbnail", None), info["webpage_url"]

                self.data = {
                    "title": title,
                    "duration": duration,
                    "thumbnail_url": thumbnail_url,
                    "webpage": webpage
                }

                await self.play_track(ctx, url=url, data=self.data, seconds=0, mode="default")
                if old_track:
                    self.queue.insert(0, old_track) # Add the previous track at index 0 so that it can be played again.

            except Exception as e:
                await ctx.send(f"An error occured while fetching track **{query}**.")
                logging.error(f"An error occured in play_now() func ; {traceback.format_exc()}")
                return

    """ Playlist system. 
    Playlists are managed through a json file called playlists.json in the bot's root
    directory, which is created if there's none at all. """

    def check_for_json(self, ctx: commands.Context) -> bool:
        """ Checks if the json file used for playlists is present, called after
        a playlist command fails with FileNotFound exception. """
        
        if not os.path.exists(PLAYLIST_FILENAME) or os.path.getsize(PLAYLIST_FILENAME) < 1:
            with open(PLAYLIST_FILENAME, "w") as f:
                data = {
                    str(ctx.guild.id): {
                        "queue": []
                    }
                }

                json.dump(data, f, indent=4)

            return False

        return True
    
    async def handle_error(self, error: str, ctx: commands.Context) -> bool:
        match error:
            case "os_error":
                await ctx.send("Failed to read playlist. Playlist file might be corrupted.")
                return True
            case "not_found":
                await ctx.send("Playlist file not found. Created one.")
                self.check_for_json(ctx)
                return True
            case "key_error":
                await ctx.send("Failed to read playlist. Playlist might be structured improperly.")
                return True
            case "unknown_error":
                await ctx.send("Unknown error occured while reading playlist file.")
                return True
            
        return False

    def read_playlist(self, file_path: str, guild_id: int) -> dict | str:
        try:
            with open(file_path, "r+") as f:
                content = json.load(f)

                if not isinstance(content, dict) or str(guild_id) not in content:
                    return "key_error"
                
                return content
                
        except (OSError, json.JSONDecodeError) as e:
            logging.error(f"Failed to read playlist file in function read_playlist(); {traceback.format_exc()}")
            return "os_error"
        except FileNotFoundError as e:
            logging.error(f"Failed to read playlist file in function read_playlist(); {traceback.format_exc()}")
            return "not_found"
        except KeyError as e:
            logging.error(f"Failed to read playlist file in function read_playlist(); {traceback.format_exc()}")
            return "key_error"
        except Exception as e:
            logging.error(f"An error occured in function read_playlist(); {traceback.format_exc()}")
            return "unknown_error"

    def write_playlist(self, file_path: str, content: dict) -> None | str:
        try:
            with open(file_path, "w") as f:
                json.dump(content, f, indent=4)

        except (OSError, json.JSONDecodeError) as e:
            logging.error(f"Failed to read playlist file in function read_playlist(); {traceback.format_exc()}")
            return "os_error"
        except FileNotFoundError as e:
            logging.error(f"Failed to read playlist file in function read_playlist(); {traceback.format_exc()}")
            return "not_found"
        except Exception as e:
            logging.error(f"An error occured in function read_playlist(); {traceback.format_exc()}")
            return "unknown_error"
        
    def get_playlist_tracks(self, tracks: list) -> str:
        tracks_string = ", ".join(title for title, webpage in tracks)
        if len(tracks_string) >= 1024:
            tracks_string = tracks_string[:1010] + " **+More...**"

        return tracks_string

    @commands.command(name="playlistcreate", help="Creates a new playlist based on the current queue.")
    async def playlistcreate(self, ctx: commands.Context) -> None:
        """ Writes a queue to the playlists.json file using the current queue as the reference. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not self.check_for_json(ctx=ctx):
            await ctx.send("No playlist file found for this server. Created one.")
        
        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if ctx.voice_client and not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if not self.queue:
            await ctx.send("The queue is empty, no tracks can be added.")
            return

        """ Create an empty array to store the track's names
        for storing the track names in the json file. """

        tracks = []
        for track in self.queue:
            tracks.append((track[1], track[4]))

        async with self.file_lock:
            data = {
                str(ctx.guild.id): {
                    "queue": tracks
                }
            }

            content = self.write_playlist(PLAYLIST_FILENAME, data)
            failed = await self.handle_error(content, ctx)
            if failed:
                return

            await ctx.send("Playlist created successfully!")
            embed = discord.Embed(
                colour=discord.Colour.random(seed=random.randint(1, 1000)),
                title="Playlist update",
                timestamp=datetime.now()
            )
            embed.add_field(name="New playlist", value=self.get_playlist_tracks(tracks), inline=False)
            await ctx.send(embed=embed)
        
    @commands.command(name="playlistadd", help="Adds one or multiple tracks to the playlist from a search query or YouTube URL.")
    async def playlistadd(self, ctx: commands.Context, *queries: str) -> None:
        """ Appends the requested queries to the playlists.json file queue. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not self.check_for_json(ctx=ctx):
            await ctx.send("No playlist file found for this server. Created one.")

        async with self.file_lock:
            current_playlist = self.read_playlist(PLAYLIST_FILENAME, ctx.guild.id)
            failed = await self.handle_error(current_playlist, ctx)
            if failed:
                return
            
            current_playlist = current_playlist[str(ctx.guild.id)]["queue"]
            new_tracks = []
            added_tracks = []
            errors = []

            async with ctx.typing():
                for query in queries:
                    try:
                        query_type = self.get_query_type(query)

                        info = await asyncio.to_thread(self.fetch_track, ctx, query_type, query)

                        if info == "no_entry":
                            errors.append((f"No entries found for query **{query}**.", "Error: No entry"))
                            continue
                        elif info == "invalid_query":
                            errors.append((f"Invalid query type for query **{query}**.", "Error: Invalid query"))
                            continue

                        if info:
                            track_tuple = (info["title"], info["webpage_url"])
                            new_tracks.append((info["title"], info["webpage_url"]))
                            if track_tuple not in current_playlist:
                                current_playlist.append((info["title"], info["webpage_url"]))
                            added_tracks.append(info["title"])
                            
                    except Exception as e:
                        errors.append((f"**{query}**", "Error: Unknown"))
                        logging.error(f"An error occured in playlistadd() func; {traceback.format_exc()}")
                        continue

                data = {
                    str(ctx.guild.id): {
                        "queue": current_playlist
                    }
                }

                content = self.write_playlist(PLAYLIST_FILENAME, data)
                failed = await self.handle_error(content, ctx)
                if failed:
                    return

                await ctx.send("Successfully updated server playlist!")
                embed = discord.Embed(
                    colour=discord.Colour.random(seed=random.randint(1, 1000)),
                    title="Playlist",
                    timestamp=datetime.now()
                )
                embed.add_field(name="Added tracks", value=self.get_single_track_queue(added_tracks), inline=False)
                if errors:
                    embed.add_field(name="Tracks not added", value="", inline=False)
                    for error in errors:
                        embed.add_field(name="", value="".join(f"**{error[0]}**: ({error[1]})\n"), inline=False)
                
                embed.add_field(name="New Playlist", value=self.get_playlist_tracks(current_playlist), inline=False)
                await ctx.send(embed=embed)

    @commands.command(name="playlistaddcurrent", help="Adds the currently playing track to the server playlist.")
    async def playlistaddcurrent(self, ctx: commands.Context) -> None:
        """ Adds the current track to the playlist by getting the title and webpage url
        from self.data, then rewrite the playlist with the current playlist plus the new track. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not self.check_for_json(ctx):
            await ctx.send("No playlist file found. Created one.")

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if ctx.voice_client and not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return

        embed = discord.Embed(
            title="Playlist update",
            colour=discord.Colour.random(seed=random.randint(1, 1000)),
            timestamp=datetime.now()
        )
        
        async with self.file_lock:
            try:
                if self.data["title"] and self.data["webpage"]:
                    current_track = (self.data["title"], self.data["webpage"])

                    queue = self.read_playlist(PLAYLIST_FILENAME, ctx.guild.id)
                    failed = await self.handle_error(queue, ctx)
                    if failed:
                        return
                    
                    playlist = queue[str(ctx.guild.id)]["queue"]

                    if playlist:
                        for title, webpage in playlist:
                            if current_track[0].lower().replace(" ", "") == title.lower().replace(" ", ""):
                                await ctx.send("Current track is already in playlist.")
                                return
                            
                        playlist.append(current_track)
                    else:
                        playlist.append(current_track)

                    data = {
                        str(ctx.guild.id): {
                            "queue": playlist
                        }
                    }

                    content = self.write_playlist(PLAYLIST_FILENAME, data)
                    failed = await self.handle_error(content, ctx)
                    if failed:
                        return
                    
                    await ctx.send("Successfully updated server playlist!")
                    embed.add_field(name="Added track", value=current_track[0], inline=False)
                    embed.add_field(name="New playlist", value=self.get_playlist_tracks(playlist), inline=False)
                    await ctx.send(embed=embed)
            except Exception as e:
                logging.error(f"Error in func playlistaddcurrent(); {traceback.format_exc()}")
                return

    @commands.command(name="playlistdelete", help="Deletes the server playlist content.")
    async def playlistdelete(self, ctx: commands.Context) -> None:
        """ Writes an empty queue to the playlists.json file. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not self.check_for_json(ctx=ctx):
            await ctx.send("No playlist file found for this server. Created one.")
            return

        try:
            async with self.file_lock:
                data = {
                    str(ctx.guild.id): {
                        "queue": []
                    }
                }

                content = self.write_playlist(PLAYLIST_FILENAME, data)
                failed = await self.handle_error(content, ctx)
                if failed:
                    return

                await ctx.send("Successfully deleted server playlist!")
        except Exception as e:
            logging.error(f"Error in func playlistdelete(); {traceback.format_exc()}")
            return

    @commands.command(name="playlistselect", help="Adds all playlist tracks to the current queue.")
    async def playlistselect(self, ctx: commands.Context) -> None:
        """ Selects the server playlist and loads it to the bot queue. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not self.check_for_json(ctx=ctx):
            await ctx.send("No playlist file found for this server. Created one.")
            return
        
        if not ctx.voice_client:
            await self.join(ctx)

        if ctx.voice_client and not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return

        async with self.file_lock:
            try:
                data = self.read_playlist(PLAYLIST_FILENAME, ctx.guild.id)
                failed = await self.handle_error(data, ctx)
                if failed:
                    return
                if data[str(ctx.guild.id)]["queue"]:
                    if self.queue:
                        await self.clear(ctx)
                    urls = []
                    for title, webpage in data[str(ctx.guild.id)]["queue"]:
                        urls.append(webpage)
                    await self.add(ctx, *urls)
                else:
                    await ctx.send("No tracks found in playlist.")
            except Exception as e:
                logging.error(f"An error occured in playlistselect() func; {traceback.format_exc()}")
                return

    @commands.command(name="playlistqueue", help="Outputs the tracks in the server playlist.")
    async def playlistqueue(self, ctx: commands.Context) -> None:
        """ Displays the current server playlist in an embed. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not self.check_for_json(ctx=ctx):
            await ctx.send("No playlist file found for this server. Created one.")
            return

        async with self.file_lock:

            playlist = self.read_playlist(PLAYLIST_FILENAME, ctx.guild.id)
            failed = await self.handle_error(playlist, ctx)
            if failed:
                return
            
            playlist = playlist[str(ctx.guild.id)]["queue"]
            if playlist:
                tracks = []
                for track, webpage in playlist:
                    tracks.append(track) # Add the playlist tracks in a new list

                embed = discord.Embed(colour=discord.Colour.random(seed=random.randint(1, 1000)),
                                        title="Playlist tracks",
                                        timestamp=datetime.now())
                embed.add_field(name="", value=self.get_single_track_queue(tracks), inline=False) # Add the new tracks to a string and send the embed.

                await ctx.send(embed=embed)
            else:
                await ctx.send("No tracks found in playlist.")

    @commands.command(name="playlistfetch", help="Fetches a track from the playlist and adds it to the queue.")
    async def playlistfetch(self, ctx: commands.Context, *tracks: str) -> None:
        """ Fetches a single (or multiple) tracks from the server playlist. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not self.check_for_json(ctx=ctx):
            await ctx.send("No playlist file found for this server. Created one.")
            return
        
        if not ctx.voice_client:
            await self.join(ctx)
        
        if ctx.voice_client and not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return

        if not tracks:
            await ctx.send("No tracks were added.")
            return

        async with self.file_lock:
            data = self.read_playlist(PLAYLIST_FILENAME, ctx.guild.id)
            failed = await self.handle_error(data, ctx)
            if failed:
                return

            if not data[str(ctx.guild.id)]["queue"]:
                await ctx.send("No tracks found in playlist.")
                return

            queue = [] # Create a new queue

            for usr_track in tracks:
                for track, webpage in data[str(ctx.guild.id)]["queue"]:
                    if usr_track.lower().replace(" ", "") in track.lower().replace(" ", ""):
                        queue.append(webpage) # Append the url to the new array.

            if queue:
                if ctx.author.voice:
                    await self.add(ctx, *queue) # Call add() and pass the new queue.
                else:
                    await ctx.send("You're not in any voice channel!")
            else:
                await ctx.send("No tracks were found.")
                return
    
    @commands.command(name="playlistremove", help="Removes a track from the server playlist.")
    async def playlistremove(self, ctx: commands.Context, *usr_tracks: str) -> None:
        """ Removes the requested tracks from the queue. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not self.check_for_json(ctx=ctx):
            await ctx.send("No playlist file found for this server. Created one.")
            return

        async with self.file_lock:
            data = self.read_playlist(PLAYLIST_FILENAME, ctx.guild.id)
            failed = await self.handle_error(data, ctx)
            if failed:
                return
            
            if not data[str(ctx.guild.id)]["queue"]:
                await ctx.send("No tracks found in playlist.")
                return

            playlist = data[str(ctx.guild.id)]["queue"]
            
            await self.remove_track(ctx, playlist, *usr_tracks)

            data = {
                str(ctx.guild.id): {
                    "queue": playlist
                }
            }
                
            content = self.write_playlist(PLAYLIST_FILENAME, data)
            failed = await self.handle_error(content, ctx)
            if failed:
                return

    @commands.command(name="playlistreposition", help="Repositions a track to a new index in the playlist.")
    async def playlistreposition(self, ctx: commands.Context, track_name: str, index: int) -> None:
        """ Repositions a track in the server playlist from its old index to a new one. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not self.check_for_json(ctx=ctx):
            await ctx.send("No playlist found for this server. Created one.")
            return

        if not self.is_modifying_playlist:
            self.is_modifying_playlist = True
        else:
            await ctx.send("Playlist is currently being modified. Please wait.")
            return

        try:
            async with self.file_lock:
                data = self.read_playlist(PLAYLIST_FILENAME, ctx.guild.id)
                failed = await self.handle_error(data, ctx)
                if failed:
                    self.is_modifying_playlist = False
                    return

                if not data[str(ctx.guild.id)]["queue"]:
                    await ctx.send("No tracks found in playlist.")
                    return

                playlist = data[str(ctx.guild.id)]["queue"]

                index -= 1
                if index < 0 or index > len(playlist):
                    await ctx.send(f"Invalid index position. Enter an index value between 1 and {len(playlist)}")
                    return

                await self.reposition_track(ctx, playlist, track_name, index)

                data = {
                    str(ctx.guild.id): {
                        "queue": playlist
                    }
                }

                content = self.write_playlist(PLAYLIST_FILENAME, data)
                failed = await self.handle_error(content, ctx)
                if failed:
                    self.is_modifying_playlist = False
                    return
        except Exception as e:
            logging.error(f"Error in func playlistreposition(); {traceback.format_exc()}")
            return
        finally:
            self.is_modifying_playlist = False

    @commands.command(name="playlistshuffle", help="Shuffles the server playlist.")
    async def playlistshuffle(self, ctx: commands.Context) -> None:
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        if not self.check_for_json(ctx):
            await ctx.send("No playlist file found. Created one.")
            return
        
        if not self.is_modifying_playlist:
            self.is_modifying_playlist = True
        else:
            await ctx.send("Playlist is currently being modified. Please wait.")
            return

        async with self.file_lock:
            embed = discord.Embed(
                title="Playlist shuffle",
                colour=discord.Colour.random(seed=random.randint(1, 1000)),
                timestamp=datetime.now()
            )
            
            content = self.read_playlist(PLAYLIST_FILENAME, ctx.guild.id)
            failed = await self.handle_error(content, ctx)
            if failed:
                self.is_modifying_playlist = False
                return
            
            if not content[str(ctx.guild.id)]["queue"]:
                await ctx.send("No tracks found in queue.")
                return
            
            playlist = content[str(ctx.guild.id)]["queue"]

            try:
                old_playlist = playlist[:]
                playlist = self.shuffle_queue(playlist) # shuffle_queue() simply returns a new list after being shuffled by random.shuffle()

                content = {
                    str(ctx.guild.id): {
                        "queue": playlist
                    }
                }

                content = self.write_playlist(PLAYLIST_FILENAME, content)
                failed = await self.handle_error(content, ctx)
                if failed:
                    self.is_modifying_playlist = False
                    return

                embed.add_field(name="The playlist has been shuffled", value="", inline=False)
                visual_queue = playlist[:]
                
                for i, (title_new, url) in enumerate(playlist):
                    old_title, old_url = old_playlist[i]
                    if title_new != old_title:
                        visual_queue[i] = (f"**{title_new}**", url)

                embed.add_field(name="New playlist", value=self.get_playlist_tracks(visual_queue), inline=True)
                embed.add_field(name="Old playlist", value=self.get_playlist_tracks(old_playlist), inline=True)

                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send("An unexpected error occured while shuffling the playlist.")
                logging.error(f"An error occured while shuffling the playlist in function playlistshuffle(); {traceback.format_exc()}")
                return
            finally:
                self.is_modifying_playlist = False

    @commands.command(name="playlistrewrite", help="Rewrites playlist file.")
    async def playlistrewrite(self, ctx: commands.Context) -> None:
        """ Fully rewrites the playlists.json file.
        Unlike playlistdelete() this function deletes the json file 
        and writes the default configuration to it. Useful to fix a broken playlist file. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not self.is_modifying_playlist:
            self.is_modifying_playlist = True
        else:
            await ctx.send("Playlist is currently being modified. Please wait.")
            return

        if os.path.exists(PLAYLIST_FILENAME):
            os.remove(PLAYLIST_FILENAME)

        data = {
            str(ctx.guild.id): {
                "queue": []
            }
        }
            
        content = self.write_playlist(PLAYLIST_FILENAME, data)
        failed = await self.handle_error(content, ctx)
        if failed:
            self.is_modifying_playlist = False
            return

        await ctx.send("Successfully rewritten server playlist.")

        self.is_modifying_playlist = False

    def get_track_index(self, queue: list, track: str) -> tuple[int, str]:
        found = False

        try:
            for index, (url, title, duration, thumbnail_url, webpage) in enumerate(queue):
                if track.lower().replace(" ", "") in title.lower().replace(" ", ""):
                    track_index = index
                    track_title = title

                    found = True
                    break
        except ValueError:
            for index, (title, url) in enumerate(queue):
                if track.lower().replace(" ", "") in title.lower().replace(" ", ""):
                    track_index = index
                    track_title = title

                    found = True
                    break

        if not found:
            return (None, None)

        return (track_index, track_title)

    @commands.command(name="getindex", help="Outputs the index of the given track in the queue.")
    async def get_index(self, ctx: commands.Context, track: str) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if not ctx.author.voice or ctx.author.voice.channel.id != ctx.voice_client.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if not self.queue:
            await ctx.send("There's nothing in the queue.")
            return
        
        if self.is_modifying_queue:
            await ctx.send("The queue is currently being modified, please wait.")
            return

        index, title = self.get_track_index(self.queue, track)
        if not index and not title:
            await ctx.send(f"Track **{track}** not found in queue.")
            return

        await ctx.send(f"Track **{title}** is at position **{index + 1}**.")

    @commands.command(name="playlistgetindex", help="Outputs the index of the given track in the server playlist.")
    async def get_index_playlist(self, ctx: commands.Context, track: str) -> None:
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if not ctx.author.voice or ctx.author.voice.channel.id != ctx.voice_client.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        if self.is_modifying_playlist:
            await ctx.send("Playlist is currently being modified. Please wait.")
            return

        content = self.read_playlist(PLAYLIST_FILENAME, ctx.guild.id)
        failed = await self.handle_error(content, ctx)
        if failed:
            return
        
        if not content[str(ctx.guild.id)]["queue"]:
            await ctx.send("No tracks found in queue.")
            return

        playlist = content[str(ctx.guild.id)]["queue"]

        index, title = self.get_track_index(playlist, track)

        if not index and not title:
            await ctx.send(f"Track **{track}** not found in playlist.")
            return
        
        await ctx.send(f"Track **{title}** is at position **{index + 1}**.")

    @commands.command(name="nowplaying", help="Outputs a load of information about the currently playing track.")
    async def nowplaying(self, ctx: commands.Context) -> None:
        """ Displays a load of information on the current track in an embed. """
        
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return

        if ctx.voice_client:
            
            try:
                embed = discord.Embed(
                    colour=discord.Colour.random(seed=random.randint(1, 1000)),
                    title="Now Playing",
                    timestamp=datetime.now()
                )
            except Exception:
                await ctx.send("Error while defining embed.")
                return

            if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                await ctx.send("I'm not currently playing anything! use '%add (search query)' to play something!")
                return

            if not ctx.voice_client.is_paused() and ctx.voice_client.is_playing():
                try:
                    self.last_elapsed_time = int(time.time() - self.start_time)
                    
                    embed.add_field(name="Current Track", value=f"{self.data["title"]}", inline=False)
                    embed.add_field(name="Track duration", value=f"{format_time(self.data["duration"])} Minutes", inline=True)
                    embed.add_field(name="Elapsed time", value=f"{format_time(self.last_elapsed_time)} Minutes", inline=True)
                    
                    if self.is_looping:
                        embed.add_field(name="Next Track", value=f"{self.data["title"]} (looping)", inline=False)
                    elif self.is_random:
                        embed.add_field(name="Next Track", value="Randomized", inline=False)
                    else:
                        if len(self.queue) > 0:
                            embed.add_field(name="Next Track", value=f"{self.queue[0][1]}", inline=False)
                        else:
                            embed.add_field(name="Next Track", value="None", inline=False)
                    
                    if len(self.queue) > 0:
                        embed.add_field(name="Queue", value=self.get_tracks(self.queue), inline=False)
                    else:
                        embed.add_field(name="Queue", value="Empty", inline=False) if not self.is_looping_queue else embed.add_field(name="Queue", value=self.get_tracks(self.queue_to_loop), inline=False)
                    embed.add_field(name="Extra Options", value=f"Looping: **{self.is_looping}**\nRandomized: **{self.is_random}**\nQueue loop: **{self.is_looping_queue}**", inline=False)
                    embed.add_field(name="Thumbnail", value="", inline=False)
                    embed.set_image(url=self.data["thumbnail_url"])

                    await ctx.send(embed=embed)
                except Exception:
                    await ctx.send(f"Error while creating embed.")
                    return
            else:
                try:
                    embed.add_field(name="**Current Track**", value=f"{self.data["title"]}", inline=False)
                    embed.add_field(name="Track duration", value=f"{format_time(self.data["duration"])} Minutes", inline=True)
                    embed.add_field(name="Elapsed time", value=f"{format_time(self.last_elapsed_time)} Minutes", inline=True)
                    
                    if self.is_random:
                        embed.add_field(name="Next Track", value="Randomized", inline=False)
                    elif self.is_looping:
                        embed.add_field(name="Next Track", value=f"{self.data["title"]} (looping)", inline=False)
                    else:
                        if len(self.queue) > 0:
                            embed.add_field(name="Next Track", value=f"{self.queue[0][1]}", inline=False)
                        else:
                            embed.add_field(name="Next Track", value="None", inline=False)
                    
                    if len(self.queue) > 0:
                        embed.add_field(name="Queue", value=self.get_tracks(self.queue), inline=False)
                    else:
                        embed.add_field(name="Queue", value="Empty", inline=False)
                    embed.add_field(name="Extra Options", value=f"Looping: **{self.is_looping}**\nRandomized: **{self.is_random}**\nQueue loop: **{self.is_looping_queue}**", inline=False)
                    embed.add_field(name="Thumbnail", value="", inline=False)
                    embed.set_image(url=self.data["thumbnail_url"])

                    await ctx.send(embed=embed)
                except Exception:
                    await ctx.send(f"Error while creating embed.")
                    return
        else:
            await ctx.send("I'm not in any voice channel!")
            return

    @commands.command(name="bitrate", help="Outputs the bitrate of the channel the bot's currently in.")
    async def get_channel_bitrate(self, ctx: commands.Context):
        meets_role_requirement = await self.check_for_role(ctx, REQUIRED_ROLE_NAME)
        if meets_role_requirement == False:
            await ctx.send("You do not have the required role to use this command.")
            return
        
        if not ctx.voice_client:
            await ctx.send("I'm not in any voice channel!")
            return
        
        if not ctx.author.voice or ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send("Join my channel first.")
            return
        
        bitrate = ctx.voice_client.channel.bitrate

        await ctx.send(f"Bitrate: {bitrate // 1000}kbps")

    @commands.command()
    async def ytsearch(self, ctx: commands.Context, query: str) -> None:
        embed = discord.Embed(
            colour=discord.Colour.random(seed=random.randint(1, 1000)),
            title="YouTube search",
            timestamp=datetime.now()
        )

        async with ctx.typing():
            try:
                query_type = self.get_query_type(query)
                
                info = await asyncio.to_thread(self.fetch_track, ctx, query_type, query)

                if info == "no_entry":
                    await ctx.send(f"No entries found for query **{query}**.")
                    return
                if info == "invalid_query":
                    await ctx.send(f"Invalid query type for query **{query}**.")
                    return

                data = {
                    "author": info.get("uploader", "Unknown"),
                    "title": info.get("title", "Unknown"),
                    "likes": "{:,}".format(info.get("like_count", 0)),
                    "views": "{:,}".format(info.get("view_count", 0)),
                    "url": info.get("webpage_url", "Unknown"),
                    "duration": format_time(info["duration"]),
                    "upload_date": info["upload_date"],
                    "description": info["description"] if not len(info["description"]) >= 1024 else info["description"][:1021] + "...",
                    "thumbnail": info.get("thumbnail"),
                }

                try:
                    date = datetime.strptime(data["upload_date"], "%Y%m%d").strftime("%d/%m/%Y")
                except ValueError:
                    date = "Unknown date"

                embed.add_field(name="Title", value=f"`{data["title"]}`", inline=True)
                embed.add_field(name="Author", value=f"`{data["author"]}`", inline=True)
                embed.add_field(name="Video statistics", value="", inline=False)
                embed.add_field(name="Views", value=f"`{data["views"]}`", inline=True)
                embed.add_field(name="Likes", value=f"`{data["likes"]}`", inline=True)
                embed.add_field(name="Description", value=f"**{data["description"]}**", inline=False)
                embed.add_field(name="URL", value=f"`{data["url"]}`", inline=False)
                embed.add_field(name="Duration", value=f"`{data['duration']} Minutes`", inline=True)
                embed.add_field(name="Upload Date", value=f"`{date}`", inline=True)
                embed.add_field(name="Thumbnail", value="", inline=False)
                embed.set_image(url=data["thumbnail"])

                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send(f"An error occured while fetching information.")
                logging.error(f"An error occured while fetching or sending information in function ytsearch(); {e}")
                return

    @commands.command()
    async def musichelp(self, ctx: commands.Context) -> None:
        embed = discord.Embed(
            title="Help",
            colour=discord.Colour.random(seed=random.randint(1, 1000)),
            timestamp=datetime.now()
        )

        try:
            embed.add_field(name="**Music Bot commands**", value="", inline=False)
            embed.add_field(name="", value=f"This documentation will guide you through all commands available within this bot.\n'**{COMMAND_PREFIX}**' is the command prefix which is used to invoke a command. **To run a command, type {COMMAND_PREFIX}<commandname>, (ex. {COMMAND_PREFIX}add)**\nThis bot partially uses slash commands.\nSome commands may require additional **parameters** provided by the user to work properly, after the command name.\nTracks are sourced from YouTube.\nAlmost all commands require the user to be in the same voice channel as the bot.", inline=False)
            embed.add_field(name=r"**Bot management commands**", value="", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}join", value="Requests the bot to join your voice channel.\nRequires the user to be in a channel and the bot in none.", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}leave", value="Requests the bot to leave the current voice channel.", inline=False)
            embed.add_field(name=r"**Player management commands**", value="", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}add **<*queries>**", value=f"Adds a track to the queue.\nProvide a search query or a YouTube URL.\nMultiple queries are supported in a single command.\nEach query **must** be enclosed in double quotes.\n(ex. {COMMAND_PREFIX}add \"C418 Haunt Muskie\" \"Resurrections Lena Raine\")\nTip: When using a standard search query, add as much **detail** as possible to get the best result, as the bot gets the first search result.", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}playnow **<query>**", value=f"Stops any track playing and plays a track extracted from the user query.\nTrack is temporary, it is not saved in the queue.\nThe previous track is re-added at the first index of the queue.\nQuery must be enclosed in double quotes.\nex. {COMMAND_PREFIX}playnow \"<trackname>\".", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}pause", value="Pauses the player.", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}resume", value="Resumes the player.", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}stop", value="Stops the current track and resets the bot's state to its defaults (join state).", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}skip", value="Skips the current track and plays the next one in the queue, if present.\nDisables loop.", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}select **<trackname>**", value=f"Selects track from the queue and plays it.\nProvide track name from the queue, use **{COMMAND_PREFIX}list** or **{COMMAND_PREFIX}nowplaying** to get all the tracks in the queue.\nSelected track is removed from the queue.\nTrack name must be enclosed in double quotes. (ex. {COMMAND_PREFIX}select \"<trackname>\", Note: Approximate track name is allowed. So something like \"<author>: <trackname>\" can be shortened to \"<trackname>\")", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}forward **<time>**", value=f"Forwards the current track by the speficied time.\nProvide a **time** value formatted to **MM:SS**.\n(ex. {COMMAND_PREFIX}forward **0:15**)\n**Note: Forwarding in very long tracks (>= 60 minutes) might not work as intended if the bot's connection is slow or unstable.**", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}rewind **<time>**", value=f"Rewinds the current track by the specified time.\nProvide a **time** value formatted to **MM:SS**.\n(ex. {COMMAND_PREFIX}rewind **0:30**)\n**Note: Rewinding in very long tracks (>= 60 minutes) might not work as intended if the bot's connection is slow or unstable.**", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}seek **<time>**", value=f"Sets the position of the current track to the specified time.\nProvide a **time** value formatted to **MM:SS**\n(ex. {COMMAND_PREFIX}seek **2:50**)\n**Note: Seeking in very long tracks (>= 60 minutes) might not work as intended if the bot's connection is slow or unstable.**", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}restart", value="Restarts the current track.", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}loop", value="Loops the currently playing track.\nFunctions as a toggle.", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}random", value="Toogle track randomization.\nIf enabled, the bot will choose a random track to play next.\nEach chosen track is removed from the queue upon selection\nFunctions as a toggle.", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}loopqueue", value=f"Loops the current queue.\nFunctions as a toggle\nCannot be enabled if **{COMMAND_PREFIX}loop** is already enabled.", inline=False)
            embed.add_field(name=r"**Track and queue information commands**", value="", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}nowplaying", value="Shows information about the current track, full queue, and more all in an embedded message.", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}list", value="Lists all the tracks in the queue.", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}history", value="Lists all previously played tracks.", inline=False)
            embed.add_field(name=f"{COMMAND_PREFIX}duration", value="Shows the track duration and the elapsed time since the start.", inline=False)
            
            embed1 = discord.Embed(
                colour=discord.Colour.random(seed=random.randint(1, 1000)),
                title="Help 2",
                timestamp=datetime.now()
            )
            
            embed1.add_field(name="**Queue management commands**", value="", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}yoink", value="Gets information on the current track and sends it to the user who sent the command.", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}remove <trackname>", value=f"Removes a track from the queue.\nRequires exact track name from the queue.\nAccepts multiple tracks surrounded by double quotes. (ex. {COMMAND_PREFIX}remove \"<track>\" \"<otherTrack>\")\nUse **{COMMAND_PREFIX}nowplaying** or **{COMMAND_PREFIX}list** to find the track name in the queue.\n(ex. {COMMAND_PREFIX}remove \"<track>\". Note: Approximate track name is allowed. So something like \"<author>: <trackname>\" can be shortened to \"<trackname>\")", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}reposition <trackname>, <index>", value=f"Repositions a **track** to a specified **position** in the queue.\nProvide the **track name** from the queue and a number between **1** and the length of the **queue**.\nTrack name **must** be enclosed in double quotes.\n(ex. {COMMAND_PREFIX}reposition \"<trackname>\" 3). Note: Approximate track name is allowed. So something like \"<author>: <trackname>\" can be shortened to \"<trackname>\"", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}clear", value="Empties the queue, removing every track.", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}removedupes", value="Removes any duplicate tracks from the queue.", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}shuffle", value="Shuffles the queue.", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}sort", value="Sorts the queue alphabetically.", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}getindex", value=f"Gets the index of the given track in the queue.\nRequires track name from the queue.\nEx. {COMMAND_PREFIX}getindex \"<track_name>\".", inline=False)
            embed1.add_field(name="**Playlist management commands**", value="", inline=False)
            embed1.add_field(name="Playlist Info", value="A server gets only **one** playlist that can be managed via these commands.", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}playlistcreate", value="Creates a playlist for the current server using the **current** queue.\nRequires a queue with atleast **1** track.\nCan only be done when there are 0 tracks in the server playlist.\nRetruns an error **if**:\nPlaylist is corrupted or non-existent.", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}playlistdelete", value="Deletes the saved server playlist.", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}playlistselect", value="Clears the current queue and adds the tracks from the saved server playlist.\nCan only be done if there are tracks in the playlist.\nReturns an error **if**:\n**- Playlist is corrupted or non-existent.**\n**- Playlist is empty**.", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}playlistadd", value=f"Add a track to the playlist.\nMultiple queries are supported and must be enclosed in double quotes.\n(ex. {COMMAND_PREFIX}playlistadd \"<trackname>\" \"<trackname>\")\nReturns an error **if**:\n**- Playlist is corrupted or non-existent.**", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}playlistaddcurrent", value="Adds the currently playing track to the playlist.\nReturns an error **if**:\nPlaylist is corrupted or non-existent.", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}playlistremove", value=f"Removes a track from the server playlist.\nRequires **track name** from the server playlist (see **{COMMAND_PREFIX}playlistqueue**).\nMultiple tracks can be removed with a single command.\n(ex.{COMMAND_PREFIX}playlistremove \"<trackname>\" \"<trackname>\"). Note: Approximate track name is allowed. So something like \"<author>: <trackname>\" can be shortened to \"<trackname>\"\nReturns an error **if**:\n**- Playlist is corrupted or non-existent.**\n**- Playlist is empty**\n**- Tracks are not found.**", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}playlistqueue", value="Lists all the tracks in the server playlist.\nReturns an error **if**:\n**- Playlist is unreadable, corrupted, or non-existent.**\n**- Playlist is empty.**", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}playlistshuffle", value="Shuffles the server playlist.\nReturns an error **if**:\n**- Playlist is unreadable, corrupted, or non-existent.**\n**- Playlist is empty.**", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}playlistfetch", value=f"Fetches a track from the server playlist (see **{COMMAND_PREFIX}playlistqueue** for tracks) and adds it to the current queue.\nTrack names **must** be enclosed in **double** quotes\nMultiple tracks can be fetched from a single command.\n(ex. {COMMAND_PREFIX}playlistfetch \"<track_name>\" \"<other_track_name>\"). Note: Approximate track name is allowed. So something like \"<author>: <trackname>\" can be shortened to \"<trackname>\"\nReturns an error **if**:\n**- Playlist is unreadable, corrupted, or non-existent.**\n**- Playlist is empty**\n**- Tracks are not found.**", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}playlistrewrite", value="Deletes playlist file and rewrites it with default configuration.\nUseful for resetting a broken file.", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}playlistgetindex", value=f"Gets the index of the given track in the server playlist.\nRequires track name from the playlist.\nEx. {COMMAND_PREFIX}playlistgetindex \"<track_name>\".\nUseful to do operations like {COMMAND_PREFIX}playlistremove on huge playlists.")
            embed1.add_field(name="Other commands", value="", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}ytsearch", value=f"Searches a video on YouTube and reports information about it in an embedded response.\nRequires a search query or YouTube URL.\n(ex. {COMMAND_PREFIX}ytsearch \"Undertale MEGALOVANIA\" or {COMMAND_PREFIX}ytsearch \"https://www.youtube.com/watch?v=XJ9XtKJHvjQ\")", inline=False)
            embed1.add_field(name=f"{COMMAND_PREFIX}bitrate", value="Outputs the bitrate of the channel the bot is in.", inline=False)

            await ctx.send(embed=embed)
            await ctx.send(embed=embed1)
        except Exception as e:
            await ctx.send(f"An error occured while sending embed.")
            logging.error(f"An error occured while creating or sending an embedded message in function musichelp(); {e}")
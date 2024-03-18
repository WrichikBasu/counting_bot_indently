"""Counting Discord bot for Indently server"""
import json
import os
import sqlite3
import string
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv('.env')

TOKEN: str = os.getenv('TOKEN')
POSSIBLE_CHARACTERS: str = string.digits + '+-*/. ()'


@dataclass
class Config:
    """Configuration for the bot"""
    channel_id: Optional[int] = None
    current_count: int = 0
    high_score: int = 0
    current_member_id: Optional[int] = None
    put_high_score_emoji: bool = False
    failed_role_id: Optional[int] = None
    reliable_counter_role_id: Optional[int] = None
    failed_member_id: Optional[int] = None
    correct_inputs_by_failed_member: int = 0

    @staticmethod
    def read():
        _config: Optional[Config] = None
        try:
            with open("config.json", "r") as file:
                _config = Config(**json.load(file))
        except FileNotFoundError:
            _config = Config()
            _config.update()
        return _config

    def update(self) -> None:
        """Update the config.json file"""
        with open("config.json", "w", encoding='utf-8') as file:
            json.dump(self.__dict__, file, indent=2)

    def increment(self, member_id: int) -> None:
        """Increment the current count and update"""
        # increment current count
        self.current_count += 1

        # update current member id
        self.current_member_id = member_id

        # check the high score
        self.high_score = max(self.high_score, self.current_count)

        self.update()

    def reset(self) -> None:
        """reset current count"""
        self.current_count = 0

        self.correct_inputs_by_failed_member = 0

        # update current member id
        self.current_member_id = None
        self.put_high_score_emoji = False

        self.update()

    def reaction_emoji(self) -> str:
        """Get the reaction emoji based on the current count"""
        if self.current_count == self.high_score and not self.put_high_score_emoji:
            emoji = "🎉"
            self.put_high_score_emoji = True
            self.update()
        elif self.current_count == 100:
            emoji = "💯"
        elif self.current_count == 69:
            emoji = "😏"
        elif self.current_count == 666:
            emoji = "👹"
        else:
            emoji = "✅"
        return emoji


class Bot(commands.Bot):
    """Counting Discord bot for Indently discord server."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        self._config: Config = Config.read()
        self._busy: int = 0
        self.failed_role: Optional[discord.Role] = None
        self.reliable_role: Optional[discord.Role] = None
        super().__init__(command_prefix='!', intents=intents)

    def update_config(self):  # TODO async def?
        # TODO dump if self.busy == 0
        # TODO create a method for force re-reading the config file - to be used from slash commands.
        pass

    async def on_ready(self) -> None:
        """Override the on_ready method"""
        print(f'Bot is ready as {self.user.name}#{self.user.discriminator}')
        if self._config.channel_id is not None and self._config.current_member_id is not None:
            channel = bot.get_channel(self._config.channel_id)
            member = await channel.guild.fetch_member(self._config.current_member_id)
            await channel.send(
                f'I\'m now online! Last counted by {member.mention}. The **next** number is '
                f'**{self._config.current_count + 1}**.')

    async def on_message(self, message: discord.Message) -> None:
        """Override the on_message method"""
        if message.author == self.user:
            return

        # TODO take out to a new method, and run only when the commands are called
        if self._config.failed_role_id is not None:
            self.failed_role = discord.utils.get(message.guild.roles, id=self._config.failed_role_id)
        else:
            self.failed_role = None
        # TODO take out to a new method, and run only when the commands are called
        if self._config.reliable_counter_role_id is not None:
            self.reliable_role = discord.utils.get(message.guild.roles, id=self._config.reliable_counter_role_id)
        else:
            self.reliable_role = None

        # Check if the message is in the channel
        if message.channel.id != self._config.channel_id:
            return

        content: str = message.content
        if not all(c in POSSIBLE_CHARACTERS for c in content) or not any(char.isdigit() for char in content):
            return

        number: int = round(eval(content))

        conn = sqlite3.connect('database.sqlite3')
        c = conn.cursor()
        c.execute('SELECT * FROM members WHERE member_id = ?', (message.author.id,))
        stats: tuple[int] = c.fetchone()

        if stats is None:
            score = 0
            correct = 0  # TODO not needed
            wrong = 0    # TODO not needed
            highest_valid_count = 0
            c.execute('INSERT INTO members VALUES(?, ?, ?, ?, ?)',
                      (message.author.id, score, correct, wrong, highest_valid_count))
            conn.commit()
        else:
            score = stats[1]
            correct = stats[2]  # TODO not needed
            wrong = stats[3]    # TODO not needed
            highest_valid_count = stats[4]

        # Wrong number
        if int(number) != int(self._config.current_count) + 1:
            await self.handle_wrong_count(message)
            c.execute('UPDATE members SET score = score - 1, wrong = wrong + 1 WHERE member_id = ?',
                      (message.author.id,))
            conn.commit()
            conn.close()
            return

        # Wrong member
        if self._config.current_count and self._config.current_member_id == message.author.id:
            await self.handle_wrong_member(message)
            c.execute('UPDATE members SET score = score - 1, wrong = wrong + 1 WHERE member_id = ?',
                      (message.author.id,))
            conn.commit()
            conn.close()
            return

        # Everything is fine
        self._config.increment(message.author.id)
        c.execute(f'''UPDATE members SET score = score + 1,
correct = correct + 1
{f", highest_valid_count  = {self._config.current_count}" if self._config.current_count > highest_valid_count else ""}
WHERE member_id = ?''',
                  (message.author.id,))
        conn.commit()
        conn.close()
        await message.add_reaction(self._config.reaction_emoji())

        # Check and add/remove reliable counter role
        # TODO: defer until not busy?
        if self.reliable_role is not None:

            if score + 1 >= 100 and self.reliable_role not in message.author.roles:  # Add role if score >= 100
                await message.author.add_roles(self.reliable_role)

            if score < 100 and self.reliable_role in message.author.roles:  # Remove role if score < 100
                await message.author.remove_roles(self.reliable_role)

        # Check and remove the failed role
        # TODO: defer until not busy?
        if self.failed_role is not None and self.failed_role in message.author.roles:
            self._config.correct_inputs_by_failed_member += 1
            if self._config.correct_inputs_by_failed_member >= 30:
                await message.author.remove_roles(self.failed_role)
                self._config.failed_member_id = None
                self._config.correct_inputs_by_failed_member = 0
            self._config.update()  # TODO use self.update_config

    async def handle_wrong_count(self, message: discord.Message) -> None:
        """Handles when someone messes up the count with a wrong number"""

        await message.channel.send(f'''{message.author.mention} messed up the count!\
The correct number was {self._config.current_count + 1}
Restart from **1** and try to beat the current high score of **{self._config.high_score}**!''')
        await message.add_reaction('❌')

        if self.failed_role is None:
            self._config.reset()  # TODO defer
            return

        # TODO defer setting role?
        if self._config.failed_member_id != message.author.id:  # Remove failed role from previous failed user
            prev_failed_member: discord.Member = await message.guild.fetch_member(self._config.failed_member_id)
            await prev_failed_member.remove_roles(self.failed_role)

        await message.author.add_roles(self.failed_role)  # Add role to current user who has failed
        self._config.failed_member_id = message.author.id  # Designate current user as failed member

        self._config.reset()  # TODO defer

    async def handle_wrong_member(self, message: discord.Message) -> None:
        """Handles when someone messes up the count by counting twice"""

        await message.channel.send(f'''{message.author.mention} messed up the count!\
You cannot count two numbers in a row!
Restart from **1** and try to beat the current high score of **{self._config.high_score}**!''')
        await message.add_reaction('❌')

        if self.failed_role is None:
            self._config.reset()  # TODO defer
            return

        if (self._config.failed_member_id is not None
                and self._config.failed_member_id != message.author.id):  # Remove role from previous failed member
            prev_failed_member: discord.Member = await message.guild.fetch_member(self._config.failed_member_id)
            await prev_failed_member.remove_roles(self.failed_role)

        await message.author.add_roles(self.failed_role)   # Add failed role to current user
        self._config.failed_member_id = message.author.id  # Designate current user as failed member

        self._config.reset()  # TODO defer

    async def on_message_delete(self, message: discord.Message) -> None:
        """Post a message in the channel if a user deletes their input."""

        if not self.is_ready():
            return

        if message.author == self.user:
            return

        # Check if the message is in the channel
        if message.channel.id != self._config.channel_id:
            return
        if not message.reactions:
            return
        if not all(c in POSSIBLE_CHARACTERS for c in message.content):
            return

        await message.channel.send(
            f'{message.author.mention} deleted their number! '
            f'The **next** number is **{self._config.current_count + 1}**.')

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        """Send a message in the channel if a user modifies their input."""

        if not self.is_ready():
            return

        if before.author == self.user:
            return

        # Check if the message is in the channel
        if before.channel.id != self._config.channel_id:
            return
        if not before.reactions:
            return
        if not all(c in POSSIBLE_CHARACTERS for c in before.content):
            return

        await after.channel.send(
            f'{after.author.mention} edited their number! The **next** number is **{self._config.current_count + 1}**.')

    async def setup_hook(self) -> None:
        await self.tree.sync()
        conn = sqlite3.connect('database.sqlite3')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS members (member_id INTEGER PRIMARY KEY,
                score INTEGER, correct INTEGER, wrong INTEGER,
                highest_valid_count INTEGER)''')
        conn.commit()
        conn.close()


bot = Bot()


@bot.tree.command(name='sync', description='Syncs the slash commands to the bot')
@app_commands.checks.has_permissions(administrator=True, ban_members=True)
async def sync(interaction: discord.Interaction):
    """Sync all the slash commands to the bot"""
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message('You do not have permission to do this!')
        return
    await interaction.response.defer()
    await bot.tree.sync()
    await interaction.followup.send('Synced!')


@bot.tree.command(name='setchannel', description='Sets the channel to count in')
@app_commands.describe(channel='The channel to count in')
@app_commands.checks.has_permissions(ban_members=True)
async def set_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Command to set the channel to count in"""
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message('You do not have permission to do this!')
        return
    config = Config.read()
    config.channel_id = channel.id
    config.update()
    await interaction.response.send_message(f'Counting channel was set to {channel.mention}')


@bot.tree.command(name='listcmds', description='Lists commands')
async def list_commands(interaction: discord.Interaction):
    """Command to list all the slash commands"""
    emb = discord.Embed(title='Slash Commands', color=discord.Color.blue(),
                        description='''
**sync** - Syncs the slash commands to the bot (Admins only)
**set_channel** - Sets the channel to count in (Admins only)
**listcmds** - Lists all the slash commands
**stats_user** - Shows the stats of a specific user
**stats_server** - Shows the stats of the server
**leaderboard** - Shows the leaderboard of the server
**set_failed_role** - Sets the role to give when a user fails (Admins only)
**set_reliable_role** - Sets the role to give when a user passes the score of 100 (Admins only)
**remove_failed_role** - Removes the role to give when a user fails (Admins only)
**remove_reliable_role** - Removes the role to give when a user passes the score of 100 (Admins only)''')
    await interaction.response.send_message(embed=emb)


@bot.tree.command(name='stats_user', description='Shows the user stats')
@app_commands.describe(member='The member to get the stats for')
async def stats_user(interaction: discord.Interaction, member: discord.Member = None):
    """Command to show the stats of a specific user"""
    await interaction.response.defer()
    if member is None:
        member = interaction.user
    emb = discord.Embed(title=f'{member.display_name}\'s stats', color=discord.Color.blue())
    conn = sqlite3.connect('database.sqlite3')
    c = conn.cursor()
    c.execute('SELECT * FROM members WHERE member_id = ?', (member.id,))
    stats = c.fetchone()
    if stats is None:
        await interaction.response.send_message('You have never counted in this server!')
        conn.close()
        return
    c.execute(f'SELECT score FROM members WHERE member_id = {member.id}')
    score = c.fetchone()[0]
    c.execute(f'SELECT COUNT(member_id) FROM members WHERE score >= {score}')
    position = c.fetchone()[0]
    conn.close()
    emb.description = f'''{member.mention}\'s stats:\n
**Score:** {stats[1]} (#{position})
**✅Correct:** {stats[2]}
**❌Wrong:** {stats[3]}
**Highest valid count:** {stats[4]}\n
**Correct rate:** {stats[1] / stats[2] * 100:.2f}%'''
    await interaction.followup.send(embed=emb)


@bot.tree.command(name="server_stats", description="View server counting stats")
async def server_stats(interaction: discord.Interaction):
    """Command to show the stats of the server"""
    config = Config.read()

    # channel not seted yet
    if config.channel_id is None:
        await interaction.response.send_message("counting channel not setted yet!")
        return

    server_stats_embed = discord.Embed(
        description=f'''**Current Count**: {config.current_count}
High Score: {config.high_score}
{f"Last counted by: <@{config.current_member_id}>" if config.current_member_id else ""}''',
        color=discord.Color.blurple()
    )
    server_stats_embed.set_author(name=interaction.guild, icon_url=interaction.guild.icon)

    await interaction.response.send_message(embed=server_stats_embed)


@bot.tree.command(name='leaderboard', description='Shows the first 10 users with the highest score')
async def leaderboard(interaction: discord.Interaction):
    """Command to show the top 10 users with the highest score in Indently"""
    await interaction.response.defer()
    emb = discord.Embed(title='Top 10 users in Indently',
                        color=discord.Color.blue(), description='')

    conn = sqlite3.connect('database.sqlite3')
    c = conn.cursor()
    c.execute('SELECT member_id, score FROM members ORDER BY score DESC LIMIT 10')
    users = c.fetchall()

    for i, user in enumerate(users, 1):
        user_obj = await interaction.guild.fetch_member(user[0])
        emb.description += f'{i}. {user_obj.mention} **{user[1]}**\n'
    conn.close()

    await interaction.followup.send(embed=emb)


@bot.tree.command(name='set_failed_role',
                  description='Sets the role to be used when a user fails to count')
@app_commands.describe(role='The role to be used when a user fails to count')
@app_commands.default_permissions(ban_members=True)
async def set_failed_role(interaction: discord.Interaction, role: discord.Role):
    """Command to set the role to be used when a user fails to count"""
    config = Config.read()
    config.failed_role_id = role.id
    config.update()
    await interaction.response.send_message(f'Failed role was set to {role.mention}')


@bot.tree.command(name='set_reliable_role',
                  description='Sets the role to be used when a user gets 100 of score')
@app_commands.describe(role='The role to be used when a user fails to count')
@app_commands.default_permissions(ban_members=True)
async def set_reliable_role(interaction: discord.Interaction, role: discord.Role):
    """Command to set the role to be used when a user gets 100 of score"""
    config = Config.read()
    config.reliable_counter_role_id = role.id
    config.update()
    await interaction.response.send_message(f'Reliable role was set to {role.mention}')


@bot.tree.command(name='remove_failed_role', description='Removes the failed role feature')
@app_commands.default_permissions(ban_members=True)
async def remove_failed_role(interaction: discord.Interaction):
    config = Config.read()
    config.failed_role_id = None
    config.update()
    await interaction.response.send_message('Failed role removed')


@bot.tree.command(name='remove_reliable_role', description='Removes the reliable role feature')
@app_commands.default_permissions(ban_members=True)
async def remove_reliable_role(interaction: discord.Interaction):
    config = Config.read()
    config.reliable_counter_role_id = None
    config.update()
    await interaction.response.send_message('Reliable role removed')


@bot.tree.command(name='disconnect', description='Makes the bot go offline')
@app_commands.default_permissions(ban_members=True)
async def disconnect(interaction: discord.Interaction):
    config = Config.read()
    if config.channel_id is not None:
        channel = bot.get_channel(config.channel_id)
        await channel.send('Bot is now offline.')
    await bot.close()


if __name__ == '__main__':
    bot.run(TOKEN)

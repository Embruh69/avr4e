# hiiii
import random
import pandas as pd
import asyncio
import markdownify
import yatg
import bs4
import pymongo
import flask
import discord
import re
import os
import d20
import gspread
import shlex
import json
import io
# import uvicorn
import requests
import traceback
from discord.ext import commands, tasks
from view import generator
import datetime
from repo import get_data
from repository import CharacterUserMapRepository, GachaMapRepository
from repository import DowntimeMapRepository
from repository import MonsterListRepository
from repository import MonstersUserMapRepository
from dnd_xml_parser import read_character_file, character_to_excel
import constant
from pagination import Paginator
from pydantic import BaseModel
from pydantic.dataclasses import dataclass, Field
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import List
from PIL import Image, ImageOps, ImageDraw
from mediawiki import MediaWiki

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
bot = commands.Bot(
    command_prefix="!",
    intents=discord.Intents.all(),
    help_command=None
)
charaRepo = None
gachaRepo = None
downtimeRepo = None
monsterRepo = None


app = FastAPI()
origins = [
    "http://localhost",
    "http://localhost:8080",
    "http://localhost:3000",
    "*",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

wiki = MediaWiki(url='https://powerlisting.fandom.com/api.php')
wiki.user_agent = 'avr4e-powerscraper'

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(bot.start(TOKEN))


@app.get("/")
async def root():
    return {"message": "{0.user}".format(bot)}


class Roll(BaseModel):
    message: str
    username: str
    dump_channel_link: str
    # example1 = {
    #     "message": "[[d20 vs ac a]][[1d8+0]]\nHmmm",
    #     "username": "aremiru",
    #     "dump_channel_link": "https://discord.com/channels/1234/1234"
    # }
    # model_config = {
    #     "json_schema_extra": {
    #         "examples": [
    #             example1
    #         ]
    #     }
    # }


@dataclass
class TargetParam():
    name: str = ""
    damage_bonus: str = ""
    d20_bonus: str = ""
    is_adv: bool = False
    is_dis: bool = False


@dataclass
class ActionParam():
    name: str = ""
    damage_bonus: str = ""
    d20_bonus: str = ""
    is_adv: bool = False
    is_dis: bool = False
    targets: List[TargetParam] = Field(default_factory=list)
    is_halved: bool = False
    thumbnail: str = ""
    is_critical: bool = False
    usages: int = 1
    multiroll: int = 1
    level: int = 0


@app.post("/roll")
async def roll(roll: Roll):
    message = process_message(roll.message)
    server_id = get_server_id(roll.dump_channel_link)
    channel_id = get_channel_id(roll.dump_channel_link)
    guild = bot.get_guild(int(server_id))
    member = guild.get_member_named(roll.username)
    channel = guild.get_channel(int(channel_id))
    await channel.send(f"<@{member.id}>\n{message}")
    return {
        "server": f"{server_id}",
        "channel": f"{channel_id}",
    }

def table_converter(html: str) -> str:
    tables = re.findall(r'<table.*>.*</table>', html)
    if len(tables) == 0:
        return html

    for table in tables:
        ascii_table = yatg.html_2_ascii_table(html_content=table, output_style="orgmode")
        html = html.replace(table, "```" + ascii_table + "```")
    return html


def to_markdown(html: str) -> str:
    html = table_converter(html)
    html = html.replace("<span", "\t|\t<span")
    md = markdownify.markdownify(html=html)
    return md


async def search_data(ctx, search, table):
    data = get_data(table, search)
    if len(data) == 0:
        await ctx.send("Not found.")
        return
    elif len(data) == 1:
        title = data[0][1]
        description = to_markdown(data[0][2])
        source = description.split("Published in ")[-1]
        description = description.split("Published in ")[0]
        if len(description) > 2000:
            description = description[:2000] + "... (too long)"
        url = "https://www.dyasdesigns.com/dnd4e/?view={}".format(data[0][3])
        embed = discord.Embed(title=title, url=url, description=description)
        embed.set_footer(text=source)
        await ctx.send(embed=embed)
        return
    else:
        idx = 1
        list = ""
        map = {}
        for x in data:
            map_key = "{}".format(idx)
            map[map_key] = x
            list = list + "`{0}. {1}`\n".format(idx, x[1])
            idx += 1

        def followup(message):
            return (
                    message.content.isnumeric() or message.content == "c"
            ) and message.author == ctx.message.author

        description = """Do you mean?\n{}""".format(list)
        embed = discord.Embed(title="Multiple Found", description=description)
        embed.set_footer(text="Type 1-10 to choose, or c to cancel.")
        option_message = await ctx.send(embed=embed)
        try:
            followup_message = await bot.wait_for(
                "message", timeout=60.0, check=followup
            )
        except asyncio.TimeoutError:
            await option_message.delete()
            await ctx.send("Time Out")
        else:
            if followup_message.content == "c":
                await option_message.delete()
                await followup_message.delete()
                return
            data = map[followup_message.content]
            title = data[1]
            description = to_markdown(data[2])
            source = description.split("Published in ")[-1]
            description = description.split("Published in ")[0]
            if len(description) > 2000:
                description = description[:2000] + "\n\n... (too long)"
            url = "https://www.dyasdesigns.com/dnd4e/?view={}".format(data[3])
            embed = discord.Embed(title=title, url=url, description=description)
            embed.set_footer(text=source)
            await option_message.delete()
            await followup_message.delete()
            await ctx.send(embed=embed)
            return

def find_inline_roll(content: str):
    pattern = r'\[\[(.*?)\]\]'
    return re.findall(pattern=pattern, string=content)


def get_server_id(url: str):
    pattern = r"https://discord.com/channels/(\d+)/(\d+)"
    match = re.search(pattern, url)

    if match:
        return match.group(1)
    else:
        return None


def get_channel_id(url: str):
    pattern = r"https://discord.com/channels/(\d+)/(\d+)"
    match = re.search(pattern, url)

    if match:
        return match.group(2)
    else:
        return None


def process_message(message: str) -> str:
    inline_rolls = find_inline_roll(message)
    if len(inline_rolls) == 0:
        return message

    for inline_roll in inline_rolls:
        result = d20.roll(inline_roll, allow_comments=True)
        if result.comment:
            inline_replacement = f"{result.comment} : {result}\n"
        else:
            inline_replacement = f"{result}\n"
        message = message.replace(f"[[{inline_roll}]]", inline_replacement, 1)
    return message


@bot.event
async def on_ready():
    daily_task_run.start()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(e)
    print("We have logged in as {0.user}".format(bot))


@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")


@bot.command()
async def help(ctx):
    embed = discord.Embed()
    embed.title = "Avr4e Commands"
    desc = ""
    desc += "## Commands List\n"
    desc += "- Add to Discord: `!add <link to sheet>`\n"
    desc += "- Update: `!update`\n"
    desc += "- View Sheet: `!sheet`\n"
    desc += "\n"
    desc += "### Actions\n"
    desc += "- List: `!a`\n"
    desc += "- Do action: `!a <action name>`\n"
    desc += "- Checks: `!c <skill name>`\n"
    desc += "- Action & Check Modifiers:\n"
    desc += "  - Adv/Dis: `!a <action> adv/dis` `!c <skill> adv/dis`\n"
    desc += "  - Situational Modifier: `!a <action> -b <amount>` "
    desc += "`!c <skill> -b <amount>`\n"
    desc += "  - Human Mode: `!a <action> -h` `!c <skill> -h`\n"
    desc += "  - Multiroll X times: `!a <action> -rr X` `!c <skill> -rr X`\n"
    desc += "  - Check Level DC: `!c <skill> -l X`\n"
    desc += "  - Action Only:\n"
    desc += "    - Situational Damage: `!a <action> -d <amount>`\n"
    desc += "    - Multi Target: `!a <action> -t <target1> -t <target2>`\n"
    desc += "    - Use X Power Point: `!action <action_name> -u X`\n"
    desc += "    - Autocrit: `!a <action_name> crit`\n"
    desc += "\n"
    desc += "**Taking Rest**\n"
    desc += "- Short Rest: `!reset sr`\n"
    desc += "- Extended Rest: `!reset`\n"
    desc += "\n"
    desc += "### Init Tracker\n"
    desc += "- Starting init: `!i begin`\n"
    desc += "- Joining init: `!i join -b <extra init bonus>`\n"
    desc += "- Adding monster/init manually: `!i add <name> <init modifier>` or `!i add <name> -p <init position>`\n"
    desc += "  Parameters:\n"
    desc += "  - AC Value: `-ac <ac number>` default 0\n"
    desc += "  - Fortitude Value: `-fort <fort number>` default 0\n"
    desc += "  - Reflex Value: `-ref <reflex number>` default 0\n"
    desc += "  - Will Value: `-will <will number>` default 0\n"
    desc += "- Editing init: `!i edit <name> -p <new init>`\n"
    desc += "- Moving init: `!i next` \n"
    desc += "- Removing init: `!i remove <name>`\n"
    desc += "- Stop init: `!i end`\n"
    desc += "\n"
    desc += "### Fun\n"
    desc += "Random superpower generator: `!sp`"
    desc += "\n"
    embed.description = desc

    await ctx.send(embed=embed)

@bot.command(name="power")
async def power_search(ctx, *, search):
    await search_data(ctx, search, "power")


@bot.command(name="item")
async def item_search(ctx, *, search):
    await search_data(ctx, search, "item")


@bot.command(name="feat")
async def feat_search(ctx, *, search):
    await search_data(ctx, search, "feat")


@bot.command(name="poison")
async def poison_search(ctx, *, search):
    await search_data(ctx, search, "poison")


@bot.command(name="ritual")
async def ritual_search(ctx, *, search):
    await search_data(ctx, search, "ritual")


@bot.command(name="weapon")
async def weapon_search(ctx, *, search):
    await search_data(ctx, search, "weapon")


@bot.command(name="theme")
async def theme_search(ctx, *, search):
    await search_data(ctx, search, "theme")


@bot.command(name="disease")
async def disease_search(ctx, *, search):
    await search_data(ctx, search, "disease")


@bot.command(name="glossary")
async def glossary_search(ctx, *, search):
    await search_data(ctx, search, "glossary")


@bot.command(name="implement")
async def implement_search(ctx, *, search):
    await search_data(ctx, search, "implement")


@bot.command(name="armor")
async def armor_search(ctx, *, search):
    await search_data(ctx, search, "armor")


@bot.command(name="companion")
async def companion_search(ctx, *, search):
    await search_data(ctx, search, "companion")


@bot.command(name="trap")
async def trap_search(ctx, *, search):
    await search_data(ctx, search, "trap")


@bot.command(name="deity")
async def deity_search(ctx, *, search):
    await search_data(ctx, search, "deity")


@bot.command(name="background")
async def background_search(ctx, *, search):
    await search_data(ctx, search, "background")


@bot.command(name="epicdestiny")
async def epicdestiny_search(ctx, *, search):
    await search_data(ctx, search, "epicdestiny")


@bot.command(name="class")
async def class_search(ctx, *, search):
    await search_data(ctx, search, "class")


@bot.command(name="monster")
async def monster_search(ctx, *, search):
    await search_data(ctx, search, "monster")


@bot.command(name="paragonpath")
async def paragonpath_search(ctx, *, search):
    await search_data(ctx, search, "paragonpath")


@bot.command(name="race")
async def race_search(ctx, *, search):
    await search_data(ctx, search, "race")

@bot.command(aliases=["add"])
async def add_sheet(ctx: commands.Context, url=""):
    try:
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        df_data = get_df(spreadsheet_id, "data")
        actions_data = get_df(spreadsheet_id, "actions")
        data_dict = create_data_dict(df_data)
        embed = create_embed(data_dict)

        # clean empty cells
        actions_data = actions_data.applymap(
            lambda x: x.strip() if isinstance(x, str) else x)
        actions_data['MaxUsages'] = actions_data['MaxUsages'].replace('', 0, )
        actions_data['Usages'] = actions_data['Usages'].replace('', 0, )
        actions_data = actions_data.replace('#REF!', None, )
        actions_data = actions_data[
            actions_data['Name'].str.strip().astype(bool)
        ]
        actions_data = actions_data.dropna()
        df_data = df_data.replace('#REF!', None)
        df_data = df_data.dropna()

        name = df_data[df_data['field_name'] == 'Name']['value'].iloc[0]
        charaRepo.set_character(
            ctx.guild.id,
            ctx.author.id,
            name,
            df_data.to_json(),
            actions_data.to_json(),
            sheet_url=url
            )
        await ctx.send(f"Sheet `{name}` is added.", embed=embed)
    except PermissionError:
        await ctx.send("Error. Please check your sheet permission.")
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["update"])
async def update_sheet(ctx: commands.Context, url=""):
    try:
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        old_actions_data = pd.read_json(io.StringIO(character[3]))
        url = character[4]
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        df_data = get_df(spreadsheet_id, "data")
        actions_data = get_df(spreadsheet_id, "actions")
        data_dict = create_data_dict(df_data)
        embed = create_embed(data_dict)

        # clean empty cells
        actions_data = actions_data.applymap(
            lambda x: x.strip() if isinstance(x, str) else x)
        actions_data['MaxUsages'] = actions_data['MaxUsages'].replace('', 0)
        actions_data['Usages'] = actions_data['Usages'].replace('', 0)
        actions_data = actions_data.replace('#REF!', None)
        actions_data = actions_data[
            actions_data['Name'].str.strip().astype(bool)
        ]
        actions_data = actions_data.dropna()
        df_data = df_data.replace('#REF!', None)
        df_data = df_data.dropna()

        old_actions_data['Usages_numeric'] = pd.to_numeric(
            old_actions_data['Usages'], errors='coerce').fillna(0)
        madf = pd.merge(
            actions_data,
            old_actions_data[['Name', 'Usages_numeric']],
            on='Name',
            how='left'
        )
        madf['Usages'] = madf['Usages_numeric'].combine_first(
            madf['Usages']
        )
        madf = madf.drop(columns=['Usages_numeric'])

        name = df_data[df_data['field_name'] == 'Name']['value'].iloc[0]
        charaRepo.set_character(
            ctx.guild.id,
            ctx.author.id,
            name,
            df_data.to_json(),
            madf.to_json(),
            sheet_url=url)
        await ctx.send(f"Sheet `{name}` is updated.", embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["sheet"])
async def char(ctx: commands.Context):
    character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
    df_data = pd.read_json(io.StringIO(character[2]))
    data_dict = create_data_dict(df_data)
    embed = create_embed(data_dict)

    await ctx.send(embed=embed)


@bot.command()
async def reset(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        actions = pd.read_json(io.StringIO(character[3]))
        if args is None:
            actions['Usages'] = actions['MaxUsages']
            message = "All actions are reset."
        else:
            max_usages = actions['MaxUsages']
            actions.loc[actions['ResetOn'] == args, 'Usages'] = max_usages
            message = f"`{args}` actions are reset."
        charaRepo.update_character(character[0], None, actions.to_json())
        embed = discord.Embed()
        embed.title = f"{character[1]}'s Actions"
        description = ""
        for i, row in actions.iterrows():
            if row['MaxUsages'] <= 0:
                continue
            usages_quota = f"({row['Usages']}/{row['MaxUsages']})"
            description += f"- **{row['Name']}** {usages_quota}\n"
        embed.description = description
        await ctx.send(message, embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["a"])
async def action(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        sheet_id = character[0]
        name = character[1]
        data = pd.read_json(io.StringIO(character[2]))
        actions = pd.read_json(io.StringIO(character[3]))
        if args is None:
            embeds = create_action_list_embed(name, actions)
            view = Paginator(ctx.author, embeds)
            if len(embeds) <= 1:
                view = None
            await ctx.send(embed=embeds[0], view=view)
            return
        else:
            args = translate_cvar(args, data)
            embed = await handle_action(args, actions, ctx, data, sheet_id)
        if embed is None:
            return
        await ctx.send(embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again. " + str(e))


@bot.command()
async def token(ctx: commands.Context, *, args=None):
    try:
        if args is None:
            await ctx.message.delete()
            character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
            data = pd.read_json(io.StringIO(character[2]))
            embed = discord.Embed()
            name = data[data['field_name'] == 'Name']['value'].iloc[0]
            token = data[data['field_name'] == 'Thumbnail']['value'].iloc[0]
            embed.title = name
            embed.set_image(url=token)
            await ctx.send(embed=embed)
        if args == "shinreigumi":
            await ctx.message.delete()
            character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
            data = pd.read_json(io.StringIO(character[2]))
            name = data[data['field_name'] == 'Name']['value'].iloc[0]
            token = data[data['field_name'] == 'Thumbnail']['value'].iloc[0]
            new_token = add_border_template(
                token, "shinreigumi_border.png", name)
            file_token = discord.File(new_token, filename=f"{name}.png")
            await ctx.send(file=file_token)
            os.remove(new_token)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


def create_action_list_embed(name: str, df: pd.DataFrame):
    max_length_description = 2500
    field_dict = {}
    embeds = []
    description = ""
    # embed.title = f"{name}'s Actions"
    try:
        for type1 in df['Type1'].unique().tolist():
            field_dict[type1] = ""
            for _, row in df[df['Type1'] == type1].iterrows():
                action_name = row['Name']
                usages = ""
                if row['MaxUsages'] > 0:
                    usages = f" ({row['Usages']}/{row['MaxUsages']})"
                type2 = ""
                if row['Type2']:
                    type2 = f" ({row['Type2']})"
                field_dict[type1] += f"- **{row['Name']}**{type2}."
                field_dict[type1] += f" {row['ShortDesc']}{usages}\n"
    except Exception:
        raise ValueError(f"Error Here: {action_name}")

    for key, value in field_dict.items():
        if key != "":
            description += f"### {key}\n"
        description += value

    i = 1
    while len(description) > max_length_description:
        embed = discord.Embed()
        embed.title = f"{name}'s Actions"
        newline_index = description[:max_length_description].rfind("\n")
        embed.description = description[:newline_index]
        embed.set_footer(text=f"Page {i}")
        embeds.append(embed)
        description = description[newline_index:]
        i += 1

    embed = discord.Embed()
    embed.title = f"{name}'s Actions"
    embed.description = description
    if i > 1:
        embed.set_footer(text=f"Page {i}")
    embeds.append(embed)

    return embeds


async def handle_action(
        command: str,
        df: pd.DataFrame,
        ctx: commands.Context,
        data: pd.DataFrame,
        sheet_id: str):
    ap = parse_command(command)
    possible_action = df[df['Name'].str.contains(
        ap.name,
        na=False,
        case=False
        )]
    ap.thumbnail = data[data['field_name'] == 'Thumbnail']['value'].iloc[0]
    name = data[data['field_name'] == 'Name']['value'].iloc[0]
    if len(possible_action) <= 0:
        await ctx.send("No actions found")
        return None
    elif len(possible_action) > 1:
        choosen = await get_user_choice(possible_action, 'Name', ctx)
        if choosen is None:
            return None
    else:
        choosen = 0
    embed = create_action_result_embed(possible_action, choosen, name, ap)
    max_usages = possible_action['MaxUsages'].iloc[choosen]
    usages = possible_action['Usages'].iloc[choosen]
    if max_usages > 0:
        action_name = possible_action['Name'].iloc[choosen]
        new_usages = usages - ap.usages
        increment = f" ({format_bonus(str(-ap.usages))})"
        if new_usages < 0:
            new_usages = usages
            embed.title = f"{name} cannot use {action_name}."
            increment = f" (Out of Usages; {format_bonus(str(-ap.usages))})"
        elif new_usages > max_usages:
            new_usages = max_usages
        usages_value = draw_quota(max_usages, new_usages)
        usages_value += increment
        embed.add_field(name=action_name, value=usages_value, inline=False)
        df.loc[df['Name'] == action_name, 'Usages'] = new_usages
        charaRepo.update_character(sheet_id, None, df.to_json())
    return embed


def parse_command(message: str) -> ActionParam:
    appended_args = [
        "-b", "-d", "adv", "dis", "-adv", "-dis"
    ]
    general_args = [
        "-h", "-crit", "-u", "crit", "-rr", "-l"
    ]
    dict_of_args = {}

    # for general args
    splitted_message = shlex.split(message)
    for idx, arg in enumerate(splitted_message):
        if arg in general_args:
            dict_of_args[arg] = idx

    splitted_message = message.split("-t")
    if len(splitted_message) < 1:
        return None
    targets_string = splitted_message[1:]
    message = splitted_message[0]

    first_arg_idx = 99
    splitted_message = shlex.split(message)
    for idx, arg in enumerate(splitted_message):
        if arg in appended_args or arg in general_args:
            if idx < first_arg_idx:
                first_arg_idx = idx
        if arg in appended_args:
            dict_of_args[arg] = idx
    action = " ".join(splitted_message[:first_arg_idx])

    param = ActionParam(
        name=action,
        damage_bonus="",
        d20_bonus="",
        is_adv=False,
        is_dis=False,
        targets=[],
        is_halved=False,
        thumbnail="",
        is_critical=False,
        usages=1
    )

    for key, value in dict_of_args.items():
        if value == -1:
            continue
        if key == "-b":
            param.d20_bonus = format_bonus(splitted_message[value+1])
        elif key == "-d":
            param.damage_bonus = format_bonus(splitted_message[value+1])
        elif key == "adv" or key == "-adv":
            param.is_adv = True
        elif key == "dis" or key == "-dis":
            param.is_dis = True
        elif key == "-h":
            param.is_halved = True
        elif key == "-crit" or key == "crit":
            param.is_critical = True
        elif key == "-u":
            param.usages = int(splitted_message[value+1])
        elif key == "-rr":
            param.multiroll = int(splitted_message[value+1])
        elif key == "-l":
            param.level = int(splitted_message[value+1])

    for idx, target_string in enumerate(targets_string):
        target = parse_target_param(target_string)
        target.d20_bonus = param.d20_bonus + target.d20_bonus
        target.damage_bonus = param.damage_bonus + target.damage_bonus
        target.is_adv = param.is_adv or target.is_adv
        target.is_dis = param.is_dis or target.is_dis
        param.targets.append(target)

    if len(param.targets) == 0:
        if param.multiroll > 1:
            for i in range(param.multiroll):
                param.targets.append(
                    TargetParam(
                        name=f"Attack {i+1}",
                        damage_bonus=param.damage_bonus,
                        d20_bonus=param.d20_bonus,
                        is_adv=param.is_adv,
                        is_dis=param.is_dis
                    )
                )
        else:
            param.targets.append(
                TargetParam(
                    name="Meta",
                    damage_bonus=param.damage_bonus,
                    d20_bonus=param.d20_bonus,
                    is_adv=param.is_adv,
                    is_dis=param.is_dis
                )
            )

    return param


def parse_target_param(message: str) -> TargetParam:
    list_of_args = [
        "-b", "-d", "adv", "dis", "-dis", "-adv"
    ]
    dict_of_args = {}

    first_arg_idx = 99
    splitted_message = shlex.split(message)
    for idx, arg in enumerate(splitted_message):
        if arg in list_of_args:
            if idx < first_arg_idx:
                first_arg_idx = idx
            dict_of_args[arg] = idx
    target_name = " ".join(splitted_message[:first_arg_idx])

    param = TargetParam(
        name=target_name,
        damage_bonus="",
        d20_bonus="",
        is_adv=False,
        is_dis=False
    )

    for key, value in dict_of_args.items():
        if value == -1:
            continue
        if key == "-b":
            param.d20_bonus = format_bonus(splitted_message[value+1])
        elif key == "-d":
            param.damage_bonus = format_bonus(splitted_message[value+1])
        elif key == "adv" or key == "-adv":
            param.is_adv = True
        elif key == "dis" or key == "-dis":
            param.is_dis = True

    return param


def translate_cvar(message, df):
    cvar = df[df['category'] == 'CVAR']
    for _, row in cvar.iterrows():
        if row["field_name"].lower() in [
                    "adv", "dis", "-t", "-b", "-d",
                    "crit", "-u", "-adv", "-dis", "crit",
                    "-h"
                ]:
            continue
        replaceable = fr"\b{re.escape(row['field_name'])}\b"
        message = re.sub(replaceable, str(row["value"]), message)
    return message


async def get_user_choice(
        choices: pd.DataFrame,
        column_name: str,
        ctx: commands.Context):
    idx = 1
    list = ""
    for _, name in choices[column_name].items():
        list += f"`{idx}. {name}`\n"
        idx += 1
        if idx > 10:
            break
    embed = discord.Embed(
            title="Multiple Found",
            description=f"Do you mean?\n{list}"
        )
    embed.set_footer(text="Type 1-10 to choose, or c to cancel.")
    option_message = await ctx.send(embed=embed)

    def followup(message: discord.Message):
        return (
            message.content.isnumeric() or message.content == "c"
            ) and message.author == ctx.message.author
    try:
        followup_message = await bot.wait_for(
                "message", timeout=60.0, check=followup
            )
    except asyncio.TimeoutError:
        await option_message.delete()
        await ctx.send("Time Out")
        return None
    else:
        await followup_message.delete()
        if followup_message.content == "c":
            await option_message.edit(content="Cancelled", embed=None)
            return None
        choosen = int(followup_message.content) - 1
        await option_message.delete()
        return choosen


def create_action_result_embed(
        possible_action: pd.DataFrame,
        choosen: int,
        name: str,
        ap: ActionParam):
    embed = discord.Embed()
    action_name = possible_action['Name'].iloc[choosen]
    embed_description = ""
    critdie = ""
    flavor = str(possible_action['Flavor'].iloc[choosen])
    effect = str(possible_action['Effect'].iloc[choosen])
    to_hit = str(possible_action['To Hit'].iloc[choosen])
    damage = str(possible_action['Damage'].iloc[choosen])
    image = str(possible_action['Image'].iloc[choosen])
    range = str(possible_action['Range'].iloc[choosen])
    def_target = str(possible_action['DefTarget'].iloc[choosen])
    if 'FreeText' in possible_action:
        embed_description = str(possible_action['FreeText'].iloc[choosen])
    if 'Critdie' in possible_action:
        critdie = format_bonus(str(possible_action['Critdie'].iloc[choosen]))
    meta = ""

    def is_aoe(range: str):
        if (
            range.lower().find("close") != -1 or
            range.lower().find("area") != -1
        ):
            return True
        return False

    embed.title = f"{name} uses {action_name}!"
    hit_description = "To Hit"
    if def_target:
        hit_description = f"To Hit vs {def_target}"
    if is_aoe(range):
        if damage:
            expression = damage + ap.damage_bonus
            expression = expression_str(expression, ap.is_halved)
            damage_result = d20.roll(expression)
            crit_expression = crit_damage_expression(expression) + critdie
            crit_result = d20.roll(crit_expression)
    for target in ap.targets:
        meta = ""
        if not ap.is_critical and to_hit:
            if to_hit[0] == "d":
                to_hit = "1"+to_hit
            if target.is_adv and target.is_dis:
                pass
            elif target.is_adv:
                to_hit = to_hit.replace("1d20", "2d20kh1")
            elif target.is_dis:
                to_hit = to_hit.replace("1d20", "2d20kl1")
            expression = to_hit + target.d20_bonus
            expression = expression_str(expression, ap.is_halved)
            hit_result = d20.roll(expression)
            meta += f"**{hit_description}**: {hit_result}\n"
        if damage and not is_aoe(range):
            expression = damage + target.damage_bonus
            expression = expression_str(expression, ap.is_halved)
            if ap.is_critical or (to_hit and hit_result.crit == 1):
                expression = crit_damage_expression(expression) + critdie
            damage_result = d20.roll(expression)
            meta += f"**Damage**: {damage_result}\n"
        elif damage and is_aoe(range):
            aoedamage = damage_result
            if ap.is_critical or (to_hit and hit_result.crit == 1):
                aoedamage = crit_result
            meta += f"**Damage**: {aoedamage}\n"
        if to_hit or damage:
            embed.add_field(name=target.name, value=meta, inline=False)
    if flavor:
        embed.add_field(name="Description", value=flavor, inline=False)
    if effect:
        embed.add_field(name="Effect", value=effect, inline=False)
    if image:
        embed.set_image(url=image)
    if ap.thumbnail:
        embed.set_thumbnail(url=ap.thumbnail)

    embed.description = embed_description
    return embed


@bot.command(aliases=["c"])
async def check(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        if args is None:
            await ctx.send("Please specify check to roll.")
            return
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        # sheet_id = character[0]
        name = character[1]
        data = pd.read_json(io.StringIO(character[2]))
        embed = await handle_check(args, data, ctx, name)
        if embed is None:
            return
        await ctx.send(embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


def perform_check_roll(
        possible_check: pd.DataFrame,
        chosen: int,
        ap: ActionParam):
    if ap.is_adv and ap.is_dis:
        dice_expr = "1d20"
    elif ap.is_adv:
        dice_expr = "2d20kh1"
    elif ap.is_dis:
        dice_expr = "2d20kl1"
    else:
        dice_expr = "1d20"

    modifier = format_number(possible_check['value'].iloc[chosen])
    check_name = possible_check['field_name'].iloc[chosen]

    base_expr = f"{dice_expr}{modifier}{ap.d20_bonus}"
    if ap.is_halved:
        base_expr = halve_flat_modifiers(base_expr)

    results = [d20.roll(base_expr) for _ in range(ap.multiroll)]
    return str(check_name), results


def create_check_result_embed(
        possible_check: pd.DataFrame,
        choosen: int,
        name: str,
        ap: ActionParam,
        level: int = 0
):
    embed = discord.Embed()
    results = []
    check_name, results = perform_check_roll(possible_check, choosen, ap)
    embed.title = f"{name} makes {check_name} check!"
    if len(results) <= 0:
        embed.description = "No such check found."
        return embed
    if len(results) == 1:
        embed.description = f"{results[0]}"
    else:
        for i in range(len(results)):
            embed.add_field(
                name=f"Check {i+1}",
                value=results[i],
                inline=True
            )
    if ap.thumbnail:
        embed.set_thumbnail(url=ap.thumbnail)
    if ap.level > 0:
        level = ap.level
    if level > 0:
        emoji = {
            "Easy": "🟢ᴇᴀꜱʏ",
            "Moderate": "🟡ᴍᴏᴅᴇʀᴀᴛᴇ",
            "Hard": "🔴ʜᴀʀᴅ",
        }
        dc = (
            " | ".join(f"{emoji[difficulty]} {value}"
                       for difficulty, value
                       in constant.LEVEL_SKILL_DC[level].items())
        )
        embed.set_footer(
            text=dc
        )
    return embed


async def handle_check(
        command: str,
        df: pd.DataFrame,
        ctx: commands.Context,
        name: str):
    ap = parse_command(command)
    rollable_check = df[df['is_rollable'] == 'TRUE']
    possible_check = rollable_check[rollable_check['field_name'].str.contains(
        ap.name, case=False
    )]
    ap.thumbnail = df[df['field_name'] == 'Thumbnail']['value'].iloc[0]
    level = df[df['field_name'] == 'Level']['value'].values
    level = parse_value(level[0])
    if len(possible_check) <= 0:
        await ctx.send("No such check found.")
        return None
    elif len(possible_check) > 1:
        choosen = await get_user_choice(possible_check, 'field_name', ctx)
        if choosen is None:
            return None
    else:
        choosen = 0
    return create_check_result_embed(possible_check, choosen, name, ap, level)


def parse_value(value) -> int:
    try:
        if type(value) is int:
            return value
        if type(value) is str:
            match = re.search(r'\d+', value)
            return int(match.group()) if match else 0
        else:
            int(value)
    except Exception:
        return 0


def get_spreadsheet_id(url: str):
    # Regular expression to match the spreadsheet ID in the URL
    pattern = r"/spreadsheets/d/([a-zA-Z0-9-_]+)"
    match = re.search(pattern, url)

    # Check if a match was found
    if match:
        return match.group(1)
    else:
        return ""


def get_df(spreadsheet_id: str, sheet_name: str):
    creds = None
    with open("credentials.json") as f:
        creds = json.load(f)
    gc = gspread.service_account_from_dict(creds)
    sheet = gc.open_by_key(spreadsheet_id)
    worksheet = sheet.worksheet(sheet_name)

    data = worksheet.get_all_records()
    return pd.DataFrame(data)


def get_all_sheets(spreadsheet_id: str) -> list:
    creds = None
    with open("credentials.json") as f:
        creds = json.load(f)
    gc = gspread.service_account_from_dict(creds)
    sheet = gc.open_by_key(spreadsheet_id)
    return sheet.worksheets()


def create_data_dict(df: pd.DataFrame) -> dict:
    result = {}
    for _, row in df.iterrows():
        category = row['category']
        field_name = row['field_name']
        value = row['value']
        is_rollable = row['is_rollable'] == 'TRUE'

        if category not in result:
            result[category] = {}

        if is_rollable:
            result[category][field_name] = format_number(value)
        else:
            result[category][field_name] = value
    return result


def create_embed(data_dict: dict) -> discord.Embed:
    embed = discord.Embed()

    for category, fields in data_dict.items():
        if category == "Special":
            embed.title = fields['Title']
            embed.description = fields['Description']
            embed.set_thumbnail(url=fields['Thumbnail'])
            embed.set_image(url=fields['Image'])
            continue
        if category == "CVAR":
            continue
        field_value = ''
        for field_name, value in fields.items():
            if is_formatted_number(str(value)):
                field_value = field_value + f"{field_name} {value}, "
                continue
            if field_name:
                field_value = field_value + f"**{field_name}**: {value}\n"
            else:
                field_value = field_value + f"{value}\n"
        field_value = field_value.rstrip(", ")
        field_value = field_value.rstrip()
        embed.add_field(name=category, value=field_value, inline=False)
    return embed


def format_number(value) -> str:
    if int(value) >= 0:
        return f"+{value}"
    else:
        return f"{value}"


def format_bonus(value: str) -> str:
    if len(value) == 0:
        return ""
    if value[0] == "+" or value[0] == "-":
        return value
    else:
        return "+" + value


def is_formatted_number(string: str):
    pattern = r'^[+-]\d+$'
    return bool(re.match(pattern, string))


def draw_quota(max_usages: int, usages: int) -> str:
    used = max_usages - usages
    if usages <= 0:
        return max_usages * "〇"
    return usages * "◉" + used * "〇"


def halve_flat_modifiers(expression: str):
    def halve_match(match):
        sign = match.group(1)
        halved_value = f"({match.group(2)}/2)"
        return f"{sign}{halved_value}"

    pattern = r'([+-])(\d+)\b'
    halved_expression = re.sub(pattern, halve_match, expression)
    return halved_expression


def expression_str(expression: str, is_halved: bool):
    if is_halved:
        expression = halve_flat_modifiers(expression)
    return expression


def crit_damage_expression(expression: str):
    pattern = r'([\d]+)d([\d]+)[khrmiaope]*[\d]*'

    def replace_dice(match):
        dice_count = match.group(1)
        dice_value = match.group(2)
        return f"({dice_count}*{dice_value})"

    modified_expression = re.sub(pattern, replace_dice, expression)

    return modified_expression


def add_border_template(url: str, template_path: str, name=""):
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Failed to download image: {response.status_code}")
    img = Image.open(io.BytesIO(response.content)).convert("RGBA")
    template = Image.open(template_path).convert("RGBA")

    # Resize the image to fit within the template's inner circle
    template_size = template.size
    img = ImageOps.fit(img, template_size, centering=(0.5, 0.5))

    # Create a circular mask for the image
    mask = Image.new('L', template_size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((1, 1, template_size[0]-1, template_size[1]-1), fill=255)

    # Apply the circular mask to the image
    img.putalpha(mask)

    # Composite the image onto the template
    image_path = f"temp/{name}.png"
    final_image = Image.alpha_composite(img, template)
    final_image.save(image_path)
    return image_path


utc = datetime.timezone.utc
times = [
    datetime.time(hour=1, tzinfo=utc)
]


def get_calendar_name() -> str:
    start_date = datetime.datetime(2025, 8, 31, 0, 0, 0, tzinfo=utc)
    now = datetime.datetime.now(utc)
    startdelta = start_date - now
    days_start = abs(startdelta.days)
    delta = now - start_date
    total_sessions = int(delta.total_seconds() // (60 * 60 * 24))
    date = get_in_game_date(total_sessions+1)
    chapter_number = (total_sessions - 1) // 7 + 1
    session_number = f"{total_sessions:02}"
    calendar_name = f"{days_start} more days from GO!"
    # calendar_name = f"{chapter_number}.{session_number} - {date}"
    return calendar_name


async def update_calendar():
    channel_calendar = bot.get_channel(1396001668633722931)
    channel_name = f"📅 {get_calendar_name()}"
    print(channel_name)
    try:
        await channel_calendar.edit(name=channel_name)
    except Exception as e:
        print(e, traceback.format_exc())


async def update_ds(guild_id: int):
    try:
        data = downtimeRepo.get_gacha(guild_id=guild_id)
        if data is None:
            print("No downtime sheet found")
            return
        url = data[4]
        if url == "":
            print("No downtime sheet found")
            return
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            print("No downtime sheet found")
            return
        sheets = get_all_sheets(spreadsheet_id)
        if len(sheets) == 0:
            print("No downtime sheet found")
            return
        df_dict = {}
        for sheet in sheets:
            if sheet.title not in ['start', 'downtime']:
                continue
            temp_df = get_df(spreadsheet_id, sheet.title)
            temp_df = temp_df.replace('#REF!', None, )
            temp_df = temp_df.dropna()
            if sheet.title == "start":
                temp_df = temp_df.sort_values(by="maxDice", ascending=True)
                start = temp_df.to_dict()
                print(start)
                continue
            if sheet.title == "downtime":
                temp_df = temp_df.applymap(
                    lambda x: x.strip() if isinstance(x, str) else x)
                temp_df['char'] = temp_df['char'].replace('', pd.NA)
                temp_df = temp_df.dropna(subset=['char'])
            df_dict[sheet.title] = temp_df.to_dict()
        downtimeRepo.set_gacha(
            guild_id=guild_id,
            start=json.dumps(start),
            items=json.dumps(df_dict),
            sheet_url=url
        )
        print("Downtime sheet is updated.")
    except Exception as e:
        print(e, traceback.format_exc())
    return


@tasks.loop(time=times)
async def daily_task_run():
    await update_calendar()
    # await update_ds(1343085306571915276)
    bot_dump_channel = bot.get_channel(1395988000474660935)
    await bot_dump_channel.send(
        "Done updating calendar and downtime.")


def get_in_game_date(week_number):
    months = [
        "Terra", "Marzen", "Saturna", "Venira",
        "Juvion", "Mercion", "Urantis", "Nevaris"
    ]

    month_weeks = []
    for i in range(8):
        if (i + 1) % 2 == 1:
            month_weeks.append(3)
        else:
            month_weeks.append(4)

    total_weeks_in_year = sum(month_weeks)
    week_in_year = (week_number - 1) % total_weeks_in_year + 1

    current_week = week_in_year
    for month_index, weeks_in_month in enumerate(month_weeks):
        if current_week <= weeks_in_month:
            week_label = {
                1: "Date of 1-8",
                2: "Date of 9-16",
                3: "Date of 17-24",
                4: "Date of 25-30"
            }[current_week]
            return f"{months[month_index]} {week_label}"
        else:
            current_week -= weeks_in_month

    raise ValueError("Invalid week number computation.")


def two_digit(number: int):
    if number < 10:
        return f"0{number}"
    return str(number)


def main():
    # uvicorn.run(app, host="0.0.0.0", port=int(os.getenv('APP_PORT')))
    bot.run(TOKEN)
    pass


@bot.command()
async def gacha(ctx: commands.Context):
    try:
        await ctx.message.delete()
        data = gachaRepo.get_gacha(ctx.guild.id)
        if data is None:
            await ctx.send("No gacha sheet is found.")
            return
        start = json.loads(data[2])
        df_dict = json.loads(data[3])
        url = data[4]
        spreadsheet_id = get_spreadsheet_id(url)
        sheet = get_sheet_to_roll(start)
        if sheet == "":
            await ctx.send("No sheet found.")
            return
        sheet_dict = df_dict[sheet]
        result = get_random_from_sheet(sheet_dict)
        sheet_df = pd.DataFrame(start)
        image = None
        try:
            image = sheet_df.loc[sheet_df['sheet'] == sheet, 'image'].values[0]
        except Exception as e:
            print(e)
        embed = discord.Embed()
        embed.title = "Gacha Result"
        embed.description = f"{result}"
        avatar_url = ""
        if ctx.author.avatar:
            avatar_url = ctx.author.avatar.url
        embed.set_image(url=image)
        embed.set_author(name=ctx.author.name, icon_url=avatar_url)
        await ctx.send(embed=embed)
        try:
            create_gacha_log_df(
                spreadsheet_id,
                ctx.channel.id,
                ctx.channel.name,
                ctx.author.id,
                ctx.author.name,
                result
            )
        except Exception as e:
            print(e)
            return
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


def get_sheet_to_roll(start: dict) -> str:
    thresholds = list(start['maxDice'].values())
    results = list(start['sheet'].values())
    max_value = max(thresholds)
    roll = random.randint(1, max_value)
    for i in range(len(thresholds)):
        if roll <= thresholds[i]:
            return results[i]
    return ""


def get_random_from_sheet(sheet_dict: dict, column_name: str = "value") -> str:
    random_value = random.choice(list(sheet_dict[column_name].values()))
    return random_value


@bot.command(aliases=["gs"])
async def gacha_sheet(ctx: commands.Context, url: str = ""):
    try:
        await ctx.message.delete()
        if url == "":
            await ctx.send("Please provide a url")
            return
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        sheets = get_all_sheets(spreadsheet_id)
        if len(sheets) == 0:
            await ctx.send("No sheets found")
            return
        df_dict = {}
        for sheet in sheets:
            temp_df = get_df(spreadsheet_id, sheet.title)
            temp_df = temp_df.replace('#REF!', None, )
            temp_df = temp_df.dropna()
            if sheet.title == "log":
                continue
            if sheet.title == "start":
                temp_df = temp_df.sort_values(by="maxDice", ascending=True)
                start = temp_df.to_dict()
                print(start)
                continue
            df_dict[sheet.title] = temp_df.to_dict()
        gachaRepo.set_gacha(
            guild_id=ctx.guild.id,
            start=json.dumps(start),
            items=json.dumps(df_dict),
            sheet_url=url
        )
        chances = calculate_gacha_chance(start)
        embed = discord.Embed()
        embed.title = "Gacha"
        embed.description = "Chances of getting each sheet are:"
        for sheet, chance in chances:
            embed.add_field(name=sheet, value=f"{chance} %", inline=False)
        await ctx.send(
                content=f"New Gacha [Spreadsheet]({url}) is added.",
                embed=embed
            )
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")
    return


@bot.command(aliases=["ds"])
async def downtime_sheet(ctx: commands.Context, url: str = ""):
    try:
        await ctx.message.delete()
        if url == "":
            await ctx.send("Please provide a url")
            return
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        sheets = get_all_sheets(spreadsheet_id)
        if len(sheets) == 0:
            await ctx.send("No sheets found")
            return
        df_dict = {}
        for sheet in sheets:
            if sheet.title not in ['start', 'downtime']:
                continue
            temp_df = get_df(spreadsheet_id, sheet.title)
            temp_df = temp_df.replace('#REF!', None, )
            temp_df = temp_df.dropna()
            if sheet.title == "start":
                temp_df = temp_df.sort_values(by="maxDice", ascending=True)
                start = temp_df.to_dict()
                print(start)
                continue
            if sheet.title == "downtime":
                temp_df = temp_df.applymap(
                    lambda x: x.strip() if isinstance(x, str) else x)
                temp_df['char'] = temp_df['char'].replace('', pd.NA)
                temp_df = temp_df.dropna(subset=['char'])
            df_dict[sheet.title] = temp_df.to_dict()
        downtimeRepo.set_gacha(
            guild_id=ctx.guild.id,
            start=json.dumps(start),
            items=json.dumps(df_dict),
            sheet_url=url
        )
        embed = discord.Embed()
        embed.title = "Downtime Gacha"
        embed.description = ". . ."
        await ctx.send(
                content=f"New Gacha [Spreadsheet]({url}) is added.",
                embed=embed
            )
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")
    return


@bot.command(aliases=["dt"])
async def downtime(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        data = downtimeRepo.get_gacha(ctx.guild.id)
        if data is None:
            await ctx.send("No downtime sheet is found.")
            return
        start = json.loads(data[2])
        df_dict = json.loads(data[3])
        url = data[4]
        spreadsheet_id = get_spreadsheet_id(url)
        sheet = get_sheet_to_roll(start)
        if sheet == "":
            await ctx.send("No sheet found.")
            return
        if sheet == "none":
            await none_meet(ctx)
            return
        filter_by_user_id: str = None
        filter_by_location: str = None
        if args is not None:
            if re.search(r'<@\d+>', args):
                filter_by_user_id = args
            else:
                filter_by_location = args
        sheet_dict = df_dict[sheet]
        sheet_df = pd.DataFrame(sheet_dict)

        # remove the userID of the person who called the command
        if 'userID' in sheet_df.columns:
            sheet_df = sheet_df[sheet_df['userID'] != f"<@{ctx.author.id}>"]

        if filter_by_user_id is not None:
            sheet_df = sheet_df[sheet_df['userID'].str.contains(
                filter_by_user_id, case=False
            )]
        if filter_by_location is not None:
            sheet_df = sheet_df[
                sheet_df['where'].isna() |
                (sheet_df['where'] == '') |
                sheet_df['where'].str.contains(
                    filter_by_location, case=False, na=False)
            ]
            unique_location = sheet_df['where'].unique().tolist()
            if len(unique_location) <= 1 and unique_location[0] == "":
                await none_meet(ctx, filter_by_location)
                return
            filter_by_location = unique_location[0]
        image = None
        character = "no one"
        location = "nowhere in particular"
        event = "No event described."
        user_id = None
        if sheet_df.empty:
            await none_meet(ctx)
            return
        try:
            random_row = sheet_df.sample(n=1).iloc[0]
            character = random_row['char']
            if random_row['where']:
                location = random_row['where']
            else:
                location = filter_by_location
            if random_row['event']:
                event = random_row['event']
            if random_row['image/gif embed']:
                image = random_row['image/gif embed']
            if random_row['userID']:
                user_id = random_row['userID']
        except Exception as e:
            print("error: ", e)
        embed = discord.Embed()
        embed.title = f"You meet with {character} at {location}!"
        if filter_by_user_id is not None:
            event = (
                f"*Fancy seeing you here… or was "
                f"this part of someone’s master plan?* 😏🕵️‍♀️\n\n{event}"
            )
        if filter_by_location is not None:
            event = (
                f"*Going to {location}, eh? "
                f"👀📍*\n\n{event}"
            )
        embed.description = (
            f"{event}\n\n"
            f"-# [*Want to add events of your character? Click this.*]({url})"
        )
        avatar_url = ""
        if ctx.author.avatar:
            avatar_url = ctx.author.avatar.url
        embed.set_image(url=image)
        embed.set_author(name=ctx.author.name, icon_url=avatar_url)
        embed.set_footer(
            text=f"DT{get_calendar_name()}"
        )
        await ctx.send(content=user_id, embed=embed)
        try:
            create_gacha_log_df(
                spreadsheet_id,
                ctx.channel.id,
                ctx.channel.name,
                ctx.author.id,
                ctx.author.name,
                character,
                event
            )
        except Exception as e:
            print(e)
            return
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


async def none_meet(ctx: commands.Context, location: str = ""):
    embed = discord.Embed()
    avatar_url = ""
    if ctx.author.avatar:
        avatar_url = ctx.author.avatar.url
    embed.set_author(name=ctx.author.name, icon_url=avatar_url)
    embed.title = "You meet no one."
    if location:
        embed.description = (
            f"*You are looking for someone at {location}…* "
            f"but no one is there.\n\n"
            f"*Maybe, try another place or people?*"
        )
    else:
        embed.description = (
            "Better luck next time.\n\nMaybe, try another place or people?"
        )
    await ctx.send(embed=embed)


def calculate_gacha_chance(data: dict):
    chances = []
    thresholds = list(data["maxDice"].values())
    sheets = list(data['sheet'].values())
    chances = []
    max_value = max(thresholds)
    for i in range(len(thresholds)):
        if i == 0:
            chance = thresholds[0]
        else:
            chance = thresholds[i] - thresholds[i - 1]
        percentage = (chance / max_value) * 100
        chances.append((sheets[i], round(percentage, 2)))

    return chances


def log_result_to_sheet(spreadsheet_id: str, df: pd.DataFrame):
    creds = None
    with open("credentials.json") as f:
        creds = json.load(f)
    gc = gspread.service_account_from_dict(creds)
    sheet = gc.open_by_key(spreadsheet_id)

    try:
        worksheet = sheet.worksheet("log")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title="log", rows="100", cols="10")
        worksheet.append_rows([df.columns.values.tolist()])
    worksheet.append_rows(df.values.tolist())

    return


def create_gacha_log_df(
            spreadsheet_id: str,
            channel_id: int,
            channel_name: str,
            user_id: int,
            user_name: str,
            result: str,
            details: str = None
        ) -> bool:
    try:
        data = {
            "timestamp":
                [datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            "channel_id": [str(channel_id)],
            "channel_name": [channel_name],
            "user_id": [str(user_id)],
            "user_name": [user_name],
            "result": [result]
        }
        if details:
            data["details"] = [details]
        log_df = pd.DataFrame(data=data)
        log_result_to_sheet(spreadsheet_id, log_df)
        return True
    except Exception as e:
        print(e, traceback.format_exc())
        return False


@bot.command(aliases=["budget"])
async def budget_calc(ctx: commands.Context, party_level: int, chara: int):
    await ctx.message.delete()
    embed = discord.Embed()
    embed.title = "XP Calculation"
    embed.url = "https://iws.mx/dnd/?view=glossary672"
    embed.description = (
        f"**Party Level**: {party_level}\n"
        f"**Character Count**: {chara}\n"
        "\n"
    )
    # easy_budget_floor = get_budget(avg_level-2, chara)
    easy_budget_ceil = get_budget(party_level-1, chara)
    # normal_budget_floor = get_budget(avg_level, chara)
    normal_budget_ceil = get_budget(party_level+1, chara)
    # hard_budget_floor = get_budget(avg_level+2, chara)
    hard_budget_ceil = get_budget(party_level+4, chara)
    embed.description += (
        f"**Easy**: {easy_budget_ceil}\n"
        f"**Normal**: {normal_budget_ceil}\n"
        f"**Hard**: {hard_budget_ceil}\n"
    )
    embed.set_footer(
        text="Rules Compendium, page(s) 285."
    )
    await ctx.send(embed=embed)


@bot.command(aliases=["generate", "gen"])
async def generate_random_encounter(
        ctx: commands.Context,
        private: str = "false",):
    is_private = private == "true"

    async def generate_callback(
            party_level: int = 1,
            chara: int = 5,
            difficulty: str = "normal",
            role: list = None,
            interaction: discord.Interaction = None):
        channel = interaction.channel
        user = interaction.user
        keywords = []
        max_budget = {}
        min_budget = {}
        floor = {}
        ceil = {}
        floor["easy"] = party_level - 2
        ceil["easy"] = party_level - 1
        min_budget["easy"] = get_budget(floor["easy"], chara)
        max_budget["easy"] = get_budget(ceil["easy"], chara)
        floor["normal"] = party_level
        ceil["normal"] = party_level + 1
        min_budget["normal"] = get_budget(floor["normal"], chara)
        max_budget["normal"] = get_budget(ceil["normal"], chara)
        floor["hard"] = party_level + 2
        ceil["hard"] = party_level + 4
        min_budget["hard"] = get_budget(floor["hard"], chara)
        max_budget["hard"] = get_budget(ceil["hard"], chara)
        floor["custom"] = party_level
        ceil["custom"] = party_level
        if difficulty == "custom":
            budget_embed = discord.Embed()
            budget_embed.title = "XP Budget for Reference"
            budget_embed.description = (
                f"**Easy**: {max_budget['easy']}\n"
                f"**Normal**: {max_budget['normal']}\n"
                f"**Hard**: {max_budget['hard']}\n"
            )
            message = await channel.send(
                content=(
                    f"Please input XP budget value. <@{user.id}>\n"
                    f"If you have any keyword you want to use, please "
                    f"add it together after a space.\nYou can add few, "
                    f"separated by space.\n"
                    f"e.g. `10000 prone slide`"
                ),
                embed=budget_embed
            )
            try:
                reply = await bot.wait_for(
                    "message",
                    timeout=60.0,
                    check=lambda m: m.author == interaction.user
                )
                custom_budget = reply.content.split()[0]
                if len(reply.content.split()) > 1:
                    keywords = reply.content.split()[1:]
                if custom_budget.isnumeric():
                    max_budget["custom"] = int(custom_budget)
                    min_budget["custom"] = 0.9 * int(custom_budget)
                else:
                    await channel.send("Invalid input.")
                    await reply.delete()
                    await message.delete()
                    return
                try:
                    await reply.delete()
                    await message.delete()
                except Exception as e:
                    print(e, traceback.format_exc())
            except asyncio.TimeoutError:
                await message.delete()
                await channel.send("Time Out")
                return
        floor[difficulty] = max(floor[difficulty]-3, 1)
        ceil[difficulty] = min(ceil[difficulty]+3, 32)
        levels = list(range(floor[difficulty], ceil[difficulty]+1))
        monster_list = monsterRepo.get_monsters_by_levels_and_roles(
            levels=levels,
            roles=role
        )
        if monster_list is None:
            await channel.send("No monsters found.")
            return None
        encounter, total_xp = generate_encounter(
            min_xp=min_budget[difficulty],
            max_xp=max_budget[difficulty],
            monster_list=monster_list,
            keywords=keywords
            )
        embed = discord.Embed()
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url
        )
        embed.title = "Encounter Generation"
        embed.description = (
            f"**Party Level**: {party_level}\n"
            f"**Character Count**: {chara}\n"
            "\n"
        )
        for monster_id, (monster_data, count) in encounter.items():
            monster_name = monster_data[1]
            monster_level = monster_data[2]
            monster_xp = monster_data[-1]
            monster_group = monster_data[4]
            monster_role = monster_data[3]
            url = f"https://iws.mx/dnd/?view={monster_data[0]}"
            embed.description += (
                f"**{count}x "
                f"[{monster_name}]({url})**:  "
                f"L{monster_level} {monster_group} "
                f"{monster_role} ({monster_xp} XP)\n"
            )
        embed.description += (
            f"\n**Total XP**: {total_xp}\n"
            f"**Budget**: {max_budget[difficulty]}\n"
        )
        if is_private:
            await interaction.user.send(embed=embed)
            return
        await channel.send(embed=embed)

    view = generator.SelectionView(ctx.author, generate_callback)
    await ctx.send(
        content=f"<@{ctx.author.id}> Select an option below to continue:",
        view=view
    )
    return


def generate_encounter(min_xp, max_xp, monster_list, keywords=[]):
    encounter = {}  # key: monster_id, value: (monster_data, count)
    total_xp = 0

    while total_xp < min_xp:
        # Filter for monsters that can fit within remaining XP
        possible_monsters = [m for m in monster_list if m[-1] > 0 and
                             total_xp + m[-1] <= max_xp]
        if not possible_monsters:
            break  # No valid monsters to add

        chosen_monster = random.choice(possible_monsters)
        monster_id = chosen_monster[0]
        monster_xp = chosen_monster[-1]
        description = chosen_monster[8]

        if keywords:
            if not any(keyword.lower() in description.lower()
                       for keyword in keywords):
                if random.random() < 0.60:
                    possible_monsters.remove(chosen_monster)
                    continue

        max_count = (max_xp - total_xp) // monster_xp
        if max_count == 0:
            continue  # Can't add even one of this monster

        monster_group = chosen_monster[4]
        if monster_group.lower() == "solo":
            max_count = min(max_count, 1)
            possible_monsters.remove(chosen_monster)
        else:
            max_count = min(max_count, 16)
        count = random.randint(1, max_count)

        if monster_id in encounter:
            encounter[monster_id] = (chosen_monster, encounter[monster_id][1]
                                     + count)
        else:
            encounter[monster_id] = (chosen_monster, count)

        total_xp += monster_xp * count

    return encounter, total_xp


def get_budget(avg_level: int, chara: int) -> int:
    if avg_level < 0 or avg_level >= len(constant.XP_LEVEL_LIST):
        return 0
    return constant.XP_LEVEL_LIST[avg_level] * chara


@bot.tree.command(name="generate", description="Random Encounter Generator")
async def random_generator_ui(
        interaction: discord.Interaction,
        private: bool = False
        ):
    async def generate_callback(
            party_level: int = 1,
            chara: int = 5,
            difficulty: str = "normal",
            role: list = None,
            interaction: discord.Interaction = None):
        channel = interaction.channel
        user = interaction.user
        keywords = []
        max_budget = {}
        min_budget = {}
        floor = {}
        ceil = {}
        floor["easy"] = party_level - 2
        ceil["easy"] = party_level - 1
        min_budget["easy"] = get_budget(floor["easy"], chara)
        max_budget["easy"] = get_budget(ceil["easy"], chara)
        floor["normal"] = party_level
        ceil["normal"] = party_level + 1
        min_budget["normal"] = get_budget(floor["normal"], chara)
        max_budget["normal"] = get_budget(ceil["normal"], chara)
        floor["hard"] = party_level + 2
        ceil["hard"] = party_level + 4
        min_budget["hard"] = get_budget(floor["hard"], chara)
        max_budget["hard"] = get_budget(ceil["hard"], chara)
        floor["custom"] = party_level
        ceil["custom"] = party_level
        if difficulty == "custom":
            budget_embed = discord.Embed()
            budget_embed.title = "XP Budget for Reference"
            budget_embed.description = (
                f"**Easy**: {max_budget['easy']}\n"
                f"**Normal**: {max_budget['normal']}\n"
                f"**Hard**: {max_budget['hard']}\n"
            )
            message = await channel.send(
                content=(
                    f"Please input XP budget value. <@{user.id}>\n"
                    f"If you have any keyword you want to use, please "
                    f"add it together after a space.\nYou can add few, "
                    f"separated by space.\n"
                    f"e.g. `10000 prone slide`"
                ),
                embed=budget_embed
            )
            try:
                reply = await bot.wait_for(
                    "message",
                    timeout=60.0,
                    check=lambda m: m.author == interaction.user
                )
                custom_budget = reply.content.split()[0]
                if len(reply.content.split()) > 1:
                    keywords = reply.content.split()[1:]
                if custom_budget.isnumeric():
                    max_budget["custom"] = int(custom_budget)
                    min_budget["custom"] = 0.9 * int(custom_budget)
                else:
                    await channel.send("Invalid input.")
                    await reply.delete()
                    await message.delete()
                    return
                try:
                    await reply.delete()
                    await message.delete()
                except Exception as e:
                    print(e, traceback.format_exc())
            except asyncio.TimeoutError:
                await message.delete()
                await channel.send("Time Out")
                return
        floor[difficulty] = max(floor[difficulty]-3, 1)
        ceil[difficulty] = min(ceil[difficulty]+3, 32)
        levels = list(range(floor[difficulty], ceil[difficulty]+1))
        monster_list = monsterRepo.get_monsters_by_levels_and_roles(
            levels=levels,
            roles=role
        )
        if monster_list is None:
            await channel.send("No monsters found.")
            return None
        encounter, total_xp = generate_encounter(
            min_xp=min_budget[difficulty],
            max_xp=max_budget[difficulty],
            monster_list=monster_list,
            keywords=keywords
            )
        embed = discord.Embed()
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url
        )
        embed.title = "Encounter Generation"
        embed.description = (
            f"**Party Level**: {party_level}\n"
            f"**Character Count**: {chara}\n"
            "\n"
        )
        for monster_id, (monster_data, count) in encounter.items():
            monster_name = monster_data[1]
            monster_level = monster_data[2]
            monster_xp = monster_data[-1]
            monster_group = monster_data[4]
            monster_role = monster_data[3]
            url = f"https://iws.mx/dnd/?view={monster_data[0]}"
            embed.description += (
                f"**{count}x "
                f"[{monster_name}]({url})**:  "
                f"L{monster_level} {monster_group} "
                f"{monster_role} ({monster_xp} XP)\n"
            )
        embed.description += (
            f"\n**Total XP**: {total_xp}\n"
            f"**Budget**: {max_budget[difficulty]}\n"
        )
        if private:
            await interaction.user.send(embed=embed)
            return
        await channel.send(embed=embed)

    view = generator.SelectionView(interaction.user, generate_callback)
    await interaction.response.send_message(
        content="Select an option below to continue:",
        view=view,
        ephemeral=True
    )


@bot.command(aliases=["madd"])
async def add_monster_sheet(ctx: commands.Context, url=""):
    try:
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        df_data = get_df(spreadsheet_id, "data")
        actions_data = get_df(spreadsheet_id, "actions")

        # clean empty cells
        actions_data = actions_data.applymap(
            lambda x: x.strip() if isinstance(x, str) else x)
        actions_data['MaxUsages'] = actions_data['MaxUsages'].replace('', 0, )
        actions_data['Usages'] = actions_data['Usages'].replace('', 0, )
        actions_data = actions_data.replace('#REF!', None, )
        actions_data = actions_data[
            actions_data['Name'].str.strip().astype(bool)
        ]
        actions_data = actions_data.dropna()
        df_data = df_data.replace('#REF!', None)
        df_data = df_data.dropna()

        name = "Monsters"
        monsterMapRepo.set_character(
            ctx.guild.id,
            ctx.author.id,
            name,
            df_data.to_json(),
            actions_data.to_json(),
            sheet_url=url
            )
        await ctx.send(f"Sheet `{name}` is added.")
    except PermissionError:
        await ctx.send("Error. Please check your sheet permission.")
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["mupdate"])
async def monster_update_sheet(ctx: commands.Context, url=""):
    try:
        character = monsterMapRepo.get_character(ctx.guild.id, ctx.author.id)
        old_actions_data = pd.read_json(io.StringIO(character[3]))
        url = character[4]
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        df_data = get_df(spreadsheet_id, "data")
        actions_data = get_df(spreadsheet_id, "actions")

        # clean empty cells
        actions_data = actions_data.applymap(
            lambda x: x.strip() if isinstance(x, str) else x)
        actions_data['MaxUsages'] = actions_data['MaxUsages'].replace('', 0)
        actions_data['Usages'] = actions_data['Usages'].replace('', 0)
        actions_data = actions_data.replace('#REF!', None)
        actions_data = actions_data[
            actions_data['Name'].str.strip().astype(bool)
        ]
        actions_data = actions_data.dropna()
        df_data = df_data.replace('#REF!', None)
        df_data = df_data.dropna()

        old_actions_data['Usages_numeric'] = pd.to_numeric(
            old_actions_data['Usages'], errors='coerce').fillna(0)
        madf = pd.merge(
            actions_data,
            old_actions_data[['Name', 'Usages_numeric']],
            on='Name',
            how='left'
        )
        madf['Usages'] = madf['Usages_numeric'].combine_first(
            madf['Usages']
        )
        madf = madf.drop(columns=['Usages_numeric'])

        name = "Monsters"
        monsterMapRepo.set_character(
            ctx.guild.id,
            ctx.author.id,
            name,
            df_data.to_json(),
            madf.to_json(),
            sheet_url=url)
        await ctx.send(f"Sheet `{name}` is updated.")
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["msheet"])
async def monster_sheet(ctx: commands.Context, *, args: str = ""):
    character = monsterMapRepo.get_character(ctx.guild.id, ctx.author.id)
    df_data = pd.read_json(io.StringIO(character[2]))
    df_actions = pd.read_json(io.StringIO(character[3]))
    possible_monster = df_data[df_data['monster_name'].str.contains(
        args,
        na=False,
        case=False
        )].drop_duplicates(subset='monster_name')
    if len(possible_monster) <= 0:
        await ctx.send("No actions found")
        return None
    elif len(possible_monster) > 1:
        choosen = await get_user_choice(possible_monster, 'monster_name', ctx)
        if choosen is None:
            return None
    else:
        choosen = 0
    monster_name = possible_monster['monster_name'].iloc[choosen]
    monster = df_data[df_data['monster_name'] == monster_name]
    monster_action = df_actions[df_actions['MonsterName'] == monster_name]

    data_dict = create_data_dict(monster)
    embed = create_embed(data_dict)

    await ctx.send(embed=embed)
    await monster_action_list(ctx, monster_action, monster_name)


async def monster_action_list(
        ctx: commands.Context,
        actions: pd.DataFrame,
        monster_name: str
):
    if actions.empty:
        await ctx.send("No actions found for this monster.")
        return None
    embeds = create_action_list_embed(monster_name, actions)
    view = Paginator(ctx.author, embeds)
    if len(embeds) <= 1:
        view = None
    await ctx.send(embed=embeds[0], view=view)


@bot.command(aliases=["mreset"])
async def monster_reset(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        character = monsterMapRepo.get_character(ctx.guild.id, ctx.author.id)
        actions = pd.read_json(io.StringIO(character[3]))
        if args is None:
            actions['Usages'] = actions['MaxUsages']
            message = "All actions are reset."
        else:
            max_usages = actions['MaxUsages']
            actions.loc[actions['ResetOn'] == args, 'Usages'] = max_usages
            message = f"`{args}` actions are reset."
        monsterMapRepo.update_character(character[0], None, actions.to_json())
        embed = discord.Embed()
        embed.title = f"{character[1]}'s Actions"
        description = ""
        for i, row in actions.iterrows():
            if row['MaxUsages'] <= 0:
                continue
            usages_quota = f"({row['Usages']}/{row['MaxUsages']})"
            description += f"- **{row['Name']}** {usages_quota}\n"
        embed.description = description
        await ctx.send(message, embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["ma"])
async def monster_action(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        character = monsterMapRepo.get_character(ctx.guild.id, ctx.author.id)
        sheet_id = character[0]
        data = pd.read_json(io.StringIO(character[2]))
        actions = pd.read_json(io.StringIO(character[3]))
        if args is None:
            await ctx.send(
                "Please specify action to roll.\n"
                "Use ;;msheet to see available actions.")
            return
        args = translate_cvar(args, data)
        embed = await handle_action_monster(args, actions, ctx, data, sheet_id)
        if embed is None:
            return
        await ctx.send(embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again. " + str(e))


async def handle_action_monster(
        command: str,
        df: pd.DataFrame,
        ctx: commands.Context,
        data: pd.DataFrame,
        sheet_id: str):
    ap = parse_command(command)
    df['ActionName'] = df['MonsterName'] + ": " + df['Name']
    possible_action = df[df['Name'].str.contains(
        ap.name,
        na=False,
        case=False
        )]
    if len(possible_action) <= 0:
        await ctx.send("No actions found")
        return None
    elif len(possible_action) > 1:
        choosen = await get_user_choice(possible_action, 'ActionName', ctx)
        if choosen is None:
            return None
    else:
        choosen = 0
    name = possible_action['MonsterName'].iloc[choosen]
    embed = create_action_result_embed(possible_action, choosen, name, ap)
    max_usages = possible_action['MaxUsages'].iloc[choosen]
    usages = possible_action['Usages'].iloc[choosen]
    if max_usages > 0:
        action_name = possible_action['Name'].iloc[choosen]
        new_usages = usages - ap.usages
        increment = f" ({format_bonus(str(-ap.usages))})"
        if new_usages < 0:
            new_usages = usages
            embed.title = f"{name} cannot use {action_name}."
            increment = f" (Out of Usages; {format_bonus(str(-ap.usages))})"
        elif new_usages > max_usages:
            new_usages = max_usages
        usages_value = draw_quota(max_usages, new_usages)
        usages_value += increment
        embed.add_field(name=action_name, value=usages_value, inline=False)
        df.loc[df['Name'] == action_name, 'Usages'] = new_usages
        charaRepo.update_character(sheet_id, None, df.to_json())
    return embed


@bot.command(aliases=["mc"])
async def monster_check(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        if args is None:
            await ctx.send("Please specify check to roll.")
            return
        character = monsterMapRepo.get_character(ctx.guild.id, ctx.author.id)
        data = pd.read_json(io.StringIO(character[2]))
        embed = await handle_check_monster(args, data, ctx)
        if embed is None:
            return
        await ctx.send(embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["i", "initiative"])
async def init(ctx: commands.Context, *args: str):
    channel_id = ctx.channel.id
    if not hasattr(bot, 'init_lists'):
        bot.init_lists = {}
    if channel_id not in bot.init_lists:
        bot.init_lists[channel_id] = {"combatants": {}, "current_turn": 0, "round": 0, "active": False}
    try:
        if not args:
            if not bot.init_lists[channel_id]["active"]:
                await ctx.send("Initiative tracking has not started. Use !i begin to start tracking initiative.")
                return

            if not bot.init_lists[channel_id]["combatants"]:
                message = f"```Current initiative: Round {bot.init_lists[channel_id]['round']}\n"
                message += "===============================\n"
                message += "No combatants have joined yet```"
                sent_message = await ctx.send(message)
                bot.init_lists[channel_id]["message_id"] = sent_message.id
                return

            sorted_init = sorted(bot.init_lists[channel_id]["combatants"].items(), key=lambda x: x[1][0], reverse=True)
            message = f"```Current initiative: {bot.init_lists[channel_id]['current_turn']} (round {bot.init_lists[channel_id]['round']})\n"
            message += "===============================\n"
            for combatant in sorted_init:
                name = combatant[0]
                initiative, ac, fort, ref, will, author_id = combatant[1]

                message += f"{name}: {initiative} (AC: {ac}, Fort: {fort}, Ref: {ref}, Will: {will})\n"
            message += "```"
            if not hasattr(bot.init_lists[channel_id], "message_id"):
                sent_message = await ctx.send(message)
                bot.init_lists[channel_id]["message_id"] = sent_message.id
            else:
                pinned_id = bot.init_lists[channel_id].get("pinned_message_id")
                if pinned_id:
                    try:
                        message_obj = await ctx.channel.fetch_message(pinned_id)
                        await message_obj.edit(content=message)
                    except:
                        sent_message = await ctx.send(message)
                        try:
                            await sent_message.pin()
                        except:
                            await ctx.send("⚠️ I couldn’t pin the initiative message. Please check my permissions.")
                        bot.init_lists[channel_id]["pinned_message_id"] = sent_message.id
                else:
                    sent_message = await ctx.send(message)
                    try:
                        await sent_message.pin()
                    except:
                        await ctx.send("⚠️ I couldn’t pin the initiative message. Please check my permissions.")
                    bot.init_lists[channel_id]["pinned_message_id"] = sent_message.id
            return

        if args[0] == "begin":
            bot.init_lists[channel_id] = {
                "combatants": {},
                "combatant_owners": {},
                "current_turn": 0,
                "round": 0,
                "active": True,
                "started": False
            }

            message = "```Current initiative: Round 0\n===============================\nNo combatants have joined yet```"
            sent_message = await ctx.send(message)

            # Unpin any previously pinned initiative message
            try:
                pins = await ctx.channel.pins()
                for pin in pins:
                    if pin.author == bot.user and pin.id != sent_message.id:
                        if "Current initiative" in pin.content:
                            await pin.unpin()
            except Exception:
                pass

            try:
                await sent_message.pin()
            except Exception:
                await ctx.send("⚠️ I couldn’t pin the initiative message. Please check my permissions.")

            # Store pinned message ID
            bot.init_lists[channel_id]["pinned_message_id"] = sent_message.id
            return

        if not bot.init_lists[channel_id]["active"]:
            await ctx.send("Initiative tracking has not started. Use !i begin to start tracking initiative.")
            return

        if args[0] == "join":
            character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
            if character is None:
                await ctx.send("Please add your character sheet first using !add")
                return

            data = pd.read_json(io.StringIO(character[2]))
            name = data[data['field_name'] == 'Name']['value'].iloc[0]
            init_bonus = data[data['field_name'] == 'Initiative']['value'].iloc[0]
            ac = data[data['field_name'] == '`AC`']['value'].iloc[0]
            fort = data[data['field_name'] == '`FORT`']['value'].iloc[0]
            ref = data[data['field_name'] == '`REF`']['value'].iloc[0]
            will = data[data['field_name'] == '`WILL`']['value'].iloc[0]

            if any(pd.isna(val) for val in (name, init_bonus, ac, fort, ref, will)):
                await ctx.send(
                    "Failed to fetch all required stats for initiative. Please check your character sheet contains Name, Initiative, AC, Fort, Reflex and Will.")
                return

            if name in bot.init_lists[channel_id]["combatants"]:
                await ctx.send(f"{name} has already joined initiative.")
                return

            bonus = 0
            manual_initiative = None

            if "-b" in args:
                try:
                    b_index = args.index("-b")
                    if b_index + 1 < len(args):
                        bonus = int(args[b_index + 1])
                except ValueError:
                    await ctx.send("Invalid bonus value. Bonus must be an integer.")
                    return

            if "-p" in args:
                try:
                    p_index = args.index("-p")
                    if p_index + 1 < len(args):
                        manual_initiative = int(args[p_index + 1])
                except ValueError:
                    await ctx.send("Invalid initiative value. Must be an integer.")
                    return

            try:
                if manual_initiative is not None:
                    initiative_result = manual_initiative
                    await ctx.send(f"{name} joins with preset initiative {initiative_result}")
                else:
                    total_bonus = int(init_bonus) + bonus
                    roll = d20.roll(f"1d20+{total_bonus}")
                    initiative_result = roll.total
                    await ctx.send(f"{name} rolled {roll} for initiative")

                bot.init_lists[channel_id]["combatants"][name] = [initiative_result, ac, fort, ref, will, ctx.author.id]
                await ctx.invoke(bot.get_command("i"))
            except Exception as e:
                await ctx.send(f"Error when rolling initiative: {str(e)}")

        elif args[0] == "add":
            if len(args) < 3:
                await ctx.send(
                    "Usage: \n • !i add <combatant name> -p <target initiative> [-ac <AC>] [-fort <Fort>] [-ref <Ref>] [-will <Will>]\n • !i add <combatant name> <initiative modifier> [-ac <AC>] [-fort <Fort>] [-ref <Ref>] [-will <Will>]")
                return
            try:
                name = args[1]

                # Default values
                ac = "n/a"
                fort = "n/a"
                ref = "n/a"
                will = "n/a"
                author_id = ctx.author.id

                if args[2] != "-p":
                    if args[2].replace('-', '').replace('+', '').isdigit():
                        initiative = d20.roll(f"1d20+{args[2]}").total
                    else:
                        initiative = d20.roll(f"1d20").total

                i = 2

                while i < len(args):
                    if args[i] == "-p" and i + 1 < len(args):
                        initiative = int(args[i + 1])
                        i += 2
                    elif args[i] == "-ac" and i + 1 < len(args):
                        ac = int(args[i + 1])
                        i += 2
                    elif args[i] == "-fort" and i + 1 < len(args):
                        fort = int(args[i + 1])
                        i += 2
                    elif args[i] == "-ref" and i + 1 < len(args):
                        ref = int(args[i + 1])
                        i += 2
                    elif args[i] == "-will" and i + 1 < len(args):
                        will = int(args[i + 1])
                        i += 2
                    else:
                        i += 1

                if not initiative:
                    initiative = d20.roll(f"1d20").total

                bot.init_lists[channel_id]["combatants"][name] = [initiative, ac, fort, ref, will, author_id]
                await ctx.send(f"Added {name} with initiative {initiative}")

                sorted_init = sorted(bot.init_lists[channel_id]["combatants"].items(), key=lambda x: x[1][0],
                                     reverse=True)
                message = f"```Current initiative: {bot.init_lists[channel_id]['current_turn']} (round {bot.init_lists[channel_id]['round']})\n"
                message += "===============================\n"
                for name, init in sorted_init:
                    message += f"{name}: {init[0]} (AC: {init[1]}, Fort: {init[2]}, Ref: {init[3]}, Will: {init[4]})\n"
                message += "```"
                pinned_id = bot.init_lists[channel_id].get("pinned_message_id")
                if pinned_id:
                    try:
                        message_obj = await ctx.channel.fetch_message(pinned_id)
                        await message_obj.edit(content=message)
                    except:
                        sent_message = await ctx.send(message)
                        try:
                            await sent_message.pin()
                        except:
                            await ctx.send("⚠️ I couldn’t pin the initiative message. Please check my permissions.")
                        bot.init_lists[channel_id]["pinned_message_id"] = sent_message.id
                else:
                    sent_message = await ctx.send(message)
                    try:
                        await sent_message.pin()
                    except:
                        await ctx.send("⚠️ I couldn’t pin the initiative message. Please check my permissions.")
                    bot.init_lists[channel_id]["pinned_message_id"] = sent_message.id
            except ValueError:
                await ctx.send("Initiative must be a number")


        elif args[0] == "edit":
            if len(args) < 2:
                await ctx.send(
                    "Usage: !i edit <combatant name> [-p <initiative>] [-ac <AC>] [-fort <Fort>] [-ref <Ref>] [-will <Will>]")
                return

            partial_name = args[1].lower()
            combatants = bot.init_lists[channel_id]["combatants"]

            matched_name = None
            for combatant_name in combatants:
                if partial_name in combatant_name.lower():
                    matched_name = combatant_name
                    break

            if matched_name is None:
                await ctx.send(f"No combatant matching '{partial_name}' found in the initiative tracker.")
                return

            current_data = combatants[matched_name]

            if not isinstance(current_data, list) or len(current_data) != 6:
                await ctx.send(f"Corrupted data for {matched_name}, unable to update.")

                return
            initiative, ac, fort, ref, will, author_id = current_data

            i = 2
            while i < len(args):
                if args[i] == "-p" and i + 1 < len(args):
                    initiative = int(args[i + 1])
                    i += 2
                elif args[i] == "-ac" and i + 1 < len(args):
                    ac = int(args[i + 1])
                    i += 2
                elif args[i] == "-fort" and i + 1 < len(args):
                    fort = int(args[i + 1])
                    i += 2
                elif args[i] == "-ref" and i + 1 < len(args):
                    ref = int(args[i + 1])
                    i += 2
                elif args[i] == "-will" and i + 1 < len(args):
                    will = int(args[i + 1])
                    i += 2
                else:
                    i += 1

            combatants[matched_name] = [initiative, ac, fort, ref, will, author_id]
            await ctx.send(
                f"Updated **{matched_name}** → Initiative: {initiative}, AC: {ac}, Fort: {fort}, Ref: {ref}, Will: {will}"
            )
            sorted_init = sorted(combatants.items(), key=lambda x: x[1][0], reverse=True)
            message = f"```Current initiative: {bot.init_lists[channel_id]['current_turn']} (round {bot.init_lists[channel_id]['round']})\n"
            message += "===============================\n"
            for name, stats in sorted_init:
                ini, ac, fort, ref, will, author_id = stats
                message += f"{name}: {ini} (AC: {ac}, Fort: {fort}, Ref: {ref}, Will: {will})\n"
            message += "```"
            pinned_id = bot.init_lists[channel_id].get("pinned_message_id")
            if pinned_id:
                try:
                    message_obj = await ctx.channel.fetch_message(pinned_id)
                    await message_obj.edit(content=message)
                except:
                    sent_message = await ctx.send(message)
                    try:
                        await sent_message.pin()
                    except:
                        await ctx.send("⚠️ I couldn’t pin the initiative message. Please check my permissions.")
                    bot.init_lists[channel_id]["pinned_message_id"] = sent_message.id
            else:
                sent_message = await ctx.send(message)
                try:
                    await sent_message.pin()
                except:
                    await ctx.send("⚠️ I couldn’t pin the initiative message. Please check my permissions.")
                bot.init_lists[channel_id]["pinned_message_id"] = sent_message.id


        elif args[0] == "end":
            confirm_view = discord.ui.View()
            confirm_button = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.danger)
            cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

            async def confirm_callback(interaction):
                if interaction.user != ctx.author:
                    await interaction.response.send_message("You cannot use this button.", ephemeral=True)
                    return
                bot.init_lists[channel_id] = {"combatants": {}, "combatant_owners": {}, "current_turn": 0, "round": 0,
                                              "active": False}
                await interaction.message.edit(content="Initiative tracker cleared.", view=None)

            async def cancel_callback(interaction):
                if interaction.user != ctx.author:
                    await interaction.response.send_message("You cannot use this button.", ephemeral=True)
                    return

                await interaction.message.edit(content="Initiative tracker was not cleared.", view=None)

            confirm_button.callback = confirm_callback
            cancel_button.callback = cancel_callback
            confirm_view.add_item(confirm_button)
            confirm_view.add_item(cancel_button)
            await ctx.send("**Are you sure you want to end the initiative tracker?**", view=confirm_view)

        elif args[0] == "remove":
            if len(args) < 2:
                await ctx.send("Usage: !i remove <combatant name>")
                return

            partial = args[1].lower()
            combatants = bot.init_lists[channel_id]["combatants"]

            matches = [name for name in combatants if partial in name.lower()]
            if not matches:
                await ctx.send(f"No combatants matching '{partial}' found.")
                return

            if len(matches) == 1:
                target_name = matches[0]

                confirm_view = discord.ui.View()
                confirm_button = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.danger)
                cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

                async def confirm_callback(interaction):
                    if interaction.user != ctx.author:
                        await interaction.response.send_message("You cannot use this button.", ephemeral=True)
                        return
                    del combatants[target_name]
                    await interaction.message.edit(content=f"Removed **{target_name}** from initiative.", view=None)
                    await ctx.invoke(bot.get_command("i"))

                async def cancel_callback(interaction):
                    if interaction.user != ctx.author:
                        await interaction.response.send_message("You cannot use this button.", ephemeral=True)
                        return
                    await interaction.message.edit(content="Removal cancelled.", view=None)

                confirm_button.callback = confirm_callback
                cancel_button.callback = cancel_callback
                confirm_view.add_item(confirm_button)
                confirm_view.add_item(cancel_button)

                await ctx.send(f"Are you sure you want to remove **{target_name}** from initiative?", view=confirm_view)
            else:
                bot.init_lists[channel_id]["pending_remove"] = {
                    "user_id": ctx.author.id,
                    "candidates": matches
                }

                embed = discord.Embed(
                    title="Multiple matches found",
                    description="Which combatant are you trying to remove?",
                    color=discord.Color.red()
                )
                for i, name in enumerate(matches, 1):
                    embed.add_field(name=f"{i}.", value=name, inline=False)

                embed.set_footer(text="Reply with the number of the combatant you want to remove.")
                await ctx.send(embed=embed)

                def check(m):
                    return (
                            m.author.id == ctx.author.id
                            and m.channel.id == ctx.channel.id
                            and m.content.isdigit()
                    )

                try:
                    msg = await bot.wait_for("message", check=check, timeout=30.0)
                    index = int(msg.content) - 1
                    candidates = bot.init_lists[channel_id]["pending_remove"]["candidates"]
                    if index < 0 or index >= len(candidates):
                        await ctx.send("Invalid selection number. Removal cancelled.")
                        del bot.init_lists[channel_id]["pending_remove"]
                        return

                    target_name = candidates[index]

                    # Confirm removal
                    confirm_view = discord.ui.View()
                    confirm_button = discord.ui.Button(label="Confirm", style=discord.ButtonStyle.danger)
                    cancel_button = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

                    async def confirm_callback(interaction):
                        if interaction.user != ctx.author:
                            await interaction.response.send_message("You cannot use this button.", ephemeral=True)
                            return
                        del combatants[target_name]
                        await interaction.message.edit(content=f"Removed **{target_name}** from initiative.", view=None)
                        await ctx.invoke(bot.get_command("i"))
                        del bot.init_lists[channel_id]["pending_remove"]

                    async def cancel_callback(interaction):
                        if interaction.user != ctx.author:
                            await interaction.response.send_message("You cannot use this button.", ephemeral=True)
                            return
                        await interaction.message.edit(content="Removal cancelled.", view=None)
                        del bot.init_lists[channel_id]["pending_remove"]

                    confirm_button.callback = confirm_callback
                    cancel_button.callback = cancel_callback
                    confirm_view.add_item(confirm_button)
                    confirm_view.add_item(cancel_button)

                    await ctx.send(f"Are you sure you want to remove **{target_name}** from initiative?", view=confirm_view)

                except asyncio.TimeoutError:
                    await ctx.send("No response received. Removal cancelled.")
                    del bot.init_lists[channel_id]["pending_remove"]

        elif args[0] == "next":
            if not bot.init_lists[channel_id]["combatants"]:
                await ctx.send("No active combat.")
                return

            sorted_init = sorted(bot.init_lists[channel_id]["combatants"].items(), key=lambda x: x[1][0], reverse=True)

            if not bot.init_lists[channel_id].get("started", False):
                bot.init_lists[channel_id]["started"] = True
                bot.init_lists[channel_id]["current_turn"] = 0
            else:
                bot.init_lists[channel_id]["current_turn"] += 1
                if bot.init_lists[channel_id]["current_turn"] >= len(sorted_init):
                    bot.init_lists[channel_id]["current_turn"] = 0
                    bot.init_lists[channel_id]["round"] += 1

            current = sorted_init[bot.init_lists[channel_id]["current_turn"]]
            combatant_name = current[0]
            initiative, ac, fort, ref, will, author_id = current[1]

            await ctx.send(f"Now it's {combatant_name}'s turn! (Initiative: {initiative}) <@" + str(author_id) + ">")

            try:
                if bot.init_lists[channel_id]["current_turn"] < len(sorted_init) - 1:
                    next_combatant = sorted_init[bot.init_lists[channel_id]["current_turn"] + 1]
                else:
                    next_combatant = sorted_init[0]
                next_name = next_combatant[0]
                next_init, _, _, _, _, next_author_id = next_combatant[1]
                await ctx.send(
                    f"Next in line is {next_name}'s turn! (Initiative: {next_init}) <@" + str(next_author_id) + ">")
            except Exception as e:
                await ctx.send(e)

            message = f"```Current initiative: {bot.init_lists[channel_id]['current_turn']} (round {bot.init_lists[channel_id]['round']})\n"
            message += "===============================\n"
            for combatant in sorted_init:
                name, stats = combatant
                message += f"{name}: {stats[0]} (AC: {stats[1]}, Fort: {stats[2]}, Ref: {stats[3]}, Will: {stats[4]})\n"
            message += "```"

            pinned_id = bot.init_lists[channel_id].get("pinned_message_id")
            if pinned_id:
                try:
                    message_obj = await ctx.channel.fetch_message(pinned_id)
                    await message_obj.edit(content=message)
                except:
                    sent_message = await ctx.send(message)
                    try:
                        await sent_message.pin()
                    except:
                        await ctx.send("⚠️ I couldn’t pin the initiative message. Please check my permissions.")
                    bot.init_lists[channel_id]["pinned_message_id"] = sent_message.id
            else:
                sent_message = await ctx.send(message)
                try:
                    await sent_message.pin()
                except:
                    await ctx.send("⚠️ I couldn’t pin the initiative message. Please check my permissions.")
                bot.init_lists[channel_id]["pinned_message_id"] = sent_message.id
        else:
            await ctx.send(f"Unrecognized subcommand: {args[0]}. Type `!help` for assistance.")

    finally:
            try:
                await ctx.message.delete()
            except:
                pass


@bot.command(aliases=["cbload"])
async def cb_generate(ctx: commands.Context):
    attachment = (
        ctx.message.attachments[0] if ctx.message.attachments else None
    )
    if attachment is None:
        await ctx.send("Please provide a file.")
        return
    file = await attachment.read()
    try:
        await ctx.message.delete()
        async with ctx.typing():
            character = await read_character_file(file)
            if character is None:
                await ctx.send("Invalid character file.")
                return
            buffer = await character_to_excel(character)
            buffer.seek(0)
            await ctx.send(
                content=(
                    f"`{character.characterName}` sheet is generated."
                ),
                file=discord.File(buffer, filename="character.xlsx")
            )
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error loading cbloader save file.")


async def handle_check_monster(
        command: str,
        df: pd.DataFrame,
        ctx: commands.Context):
    ap = parse_command(command)
    rollable_check = df[df['is_rollable'] == 'TRUE']
    rollable_check['monster_field_name'] = (
        rollable_check['monster_name'] + ": " + rollable_check['field_name']
    )
    possible_check = rollable_check[
        rollable_check['monster_field_name'].str.contains(
            ap.name, case=False
        )
    ]
    # ap.thumbnail = df[df['field_name'] == 'Thumbnail']['value'].iloc[0]
    if len(possible_check) <= 0:
        await ctx.send("No such check found.")
        return None
    elif len(possible_check) > 1:
        choosen = await get_user_choice(
            possible_check, 'monster_field_name', ctx)
        if choosen is None:
            return None
    else:
        choosen = 0
    name = possible_check['monster_name'].iloc[choosen]
    return create_check_result_embed(possible_check, choosen, name, ap)


@bot.command(aliases=['sp'])
async def superpower(ctx: commands.Context):
    try:
        # Get a random page title
        title = wiki.random(pages=1)

        # Retrieve the page by title
        page = wiki.page(title)

        # Get title and URL
        power_title = page.title
        power_url = page.url

        # Try to extract a suitable image from the list
        image_url = None
        if page.images:
            valid_images = [
                img for img in page.images
                if any(img.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif'])
                and 'logo' not in img.lower()
                and 'icon' not in img.lower()
            ]
            if valid_images:
                image_url = random.choice(valid_images)

        # Extract raw wikitext content
        raw_text = page.wikitext

        # Extract the "==Capabilities==" section using regex
        match = re.search(r'==\s*Capabilities\s*==\n(.*?)(?=\n==)', raw_text, re.DOTALL | re.IGNORECASE)
        capabilities = match.group(1).strip() if match else "No capabilities section found."

        # Clean wiki markup (very basic)
        capabilities_cleaned = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]', r'\1', capabilities)  # Replace links
        capabilities_cleaned = re.sub(r"'''(.*?)'''", r'\1', capabilities_cleaned)  # Bold
        capabilities_cleaned = re.sub(r"''(.*?)''", r'\1', capabilities_cleaned)    # Italic
        capabilities_cleaned = re.sub(r'{{[^}]+}}', '', capabilities_cleaned)       # Remove templates
        capabilities_cleaned = re.sub(r'<.*?>', '', capabilities_cleaned)           # Remove HTML tags

        # Discord Embed
        embed = discord.Embed(
            title=power_title,
            url=power_url,
            description=f"**Capabilities:**\n{capabilities_cleaned[:2045] + '...' if len(capabilities_cleaned) > 2048 else capabilities_cleaned}",
            color=discord.Color.purple()
        )

        if image_url:
            embed.set_image(url=image_url)

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"An error occurred while fetching the superpower: {str(e)}")

if __name__ == "__main__":
    charaRepo = CharacterUserMapRepository()
    gachaRepo = GachaMapRepository()
    downtimeRepo = DowntimeMapRepository()
    monsterRepo = MonsterListRepository()
    monsterMapRepo = MonstersUserMapRepository()
    main()





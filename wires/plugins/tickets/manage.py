import asyncpg
import crescent
import flare
import hikari

from wires import constants
from wires.database.models import TicketConfig
from wires.errors import (
    DuplicateTicketConfigName,
    MissingTicketConfig,
    NoTicketConfigs,
    WiresErr,
)

from .. import Plugin
from .plugin import CreateTicketButton

plugin = Plugin()
group = crescent.Group(
    "tickets",
    "Manage ticket configurations.",
    default_member_permissions=hikari.Permissions.MANAGE_GUILD,
    dm_enabled=False,
)


def clean_name(name: str) -> str:
    name = "".join([c for c in name if c.isalnum() or c == "_"])
    name_len = len(name)
    if name_len < 2 or name_len > 32:
        raise WiresErr(
            "`name` must be between 2 and 32 characters, and only consist of "
            "a-zA-Z0-9_."
        )
    return name


def validate_initial(content: str) -> None:
    if len(content) > (length := constants.MAX_MESSAGE_LENGTH):
        raise WiresErr(f"The initial message cannot be longer than {length}.")


async def ticket_config_autocomplete(
    ctx: crescent.AutocompleteContext, option: hikari.AutocompleteInteractionOption
) -> list[hikari.CommandChoice]:
    assert ctx.guild_id
    configs = await TicketConfig.fetchmany(guild_id=ctx.guild_id)
    return [
        hikari.CommandChoice(name=config.name, value=config.name) for config in configs
    ]


@plugin.include
@group.child
@crescent.command(name="list", description="List existing ticket configurations.")
class ListTicketConfigs:
    async def callback(self, ctx: crescent.Context) -> None:
        assert ctx.guild_id
        configs = await TicketConfig.fetchmany(guild_id=ctx.guild_id)

        if not len(configs):
            raise NoTicketConfigs()

        embed = hikari.Embed(color=constants.EMBED_DARK_BG)
        for config in configs:
            embed.add_field(config.name, f"<#{config.channel}>", inline=True)

        await ctx.respond(embed=embed)


@plugin.include
@group.child
@crescent.command(name="new", description="Create a new ticket configuration.")
class NewTicketConfig:
    channel = crescent.option(
        hikari.TextableGuildChannel, "The channel to open ticket threads in."
    )
    name = crescent.option(
        str, "The name of the ticket configuration.", max_length=32, min_length=2
    )
    initial = crescent.option(
        str,
        "The initial message to send in a new ticket.",
        max_length=constants.MAX_MESSAGE_LENGTH,
        default=None,
    )

    async def callback(self, ctx: crescent.Context) -> None:
        assert ctx.guild_id

        name = clean_name(self.name)
        if self.initial:
            validate_initial(self.initial)

        try:
            await TicketConfig(
                name=name,
                channel=self.channel.id,
                guild_id=ctx.guild_id,
                initial_message_content=self.initial,
            ).create()
        except asyncpg.UniqueViolationError:
            raise DuplicateTicketConfigName(name)

        await ctx.respond(
            f"Created config '{name}'. Use `/tickets entrypoint` to send an entrypoint "
            "message.",
        )


@plugin.include
@group.child
@crescent.command(name="delete", description="Delete a ticket configuration.")
class DeleteTicketConfiguration:
    name = crescent.option(
        str,
        "The name of the ticket configuration.",
        autocomplete=ticket_config_autocomplete,
    )

    async def callback(self, ctx: crescent.Context) -> None:
        assert ctx.guild_id
        config = (
            await TicketConfig.delete_query()
            .where(guild_id=ctx.guild_id, name=self.name)
            .execute()
        )
        if not len(config):
            raise MissingTicketConfig(self.name)
        await ctx.respond(f"Deleted ticket configuration '{self.name}'.")


@plugin.include
@group.child
@crescent.command(name="rename", description="Rename a ticket configuration.")
class RenameTicketConfiguration:
    name = crescent.option(
        str,
        "The name of the ticket configuration.",
        autocomplete=ticket_config_autocomplete,
    )
    new_name = crescent.option(
        str,
        "The new name of the ticket configuration.",
        autocomplete=ticket_config_autocomplete,
        name="new-name",
    )

    async def callback(self, ctx: crescent.Context) -> None:
        assert ctx.guild_id

        config = await TicketConfig.exists(guild_id=ctx.guild_id, name=self.name)
        if not config:
            raise MissingTicketConfig(self.name)

        config.name = name = clean_name(self.new_name)
        try:
            await config.save()
        except asyncpg.UniqueViolationError:
            raise DuplicateTicketConfigName(name)

        await ctx.respond("Renamed ticket configuration.")


@plugin.include
@group.child
@crescent.command(name="edit-initial", description="Edit the initial message.")
class EditInitialMessage:
    name = crescent.option(
        str,
        "The name of the ticket configuration.",
        autocomplete=ticket_config_autocomplete,
    )
    initial = crescent.option(
        str,
        "The initial message to send in a new ticket.",
        max_length=constants.MAX_MESSAGE_LENGTH,
        default=None,
    )

    async def callback(self, ctx: crescent.Context) -> None:
        assert ctx.guild_id

        if self.initial:
            validate_initial(self.initial)

        config = await TicketConfig.exists(guild_id=ctx.guild_id, name=self.name)
        if not config:
            raise MissingTicketConfig(self.name)

        config.initial_message_content = self.initial
        await config.save()
        await ctx.respond("Updated ticket configuration.")


@plugin.include
@group.child
@crescent.command(
    name="entrypoint",
    description="Create an entrypoint message for a ticket configuration.",
)
class CreateEntrypoint:
    name = crescent.option(
        str,
        "The name of the ticket configuration to create an entrypoint for.",
        autocomplete=ticket_config_autocomplete,
    )
    content = crescent.option(str, "The content of the message.")
    button = crescent.option(str, "The button label.")

    async def callback(self, ctx: crescent.Context) -> None:
        assert ctx.guild_id
        config = await TicketConfig.fetch(guild_id=ctx.guild_id, name=self.name)

        if config is None:
            raise MissingTicketConfig(self.name)

        button = CreateTicketButton(config.id).set_label(self.button)
        row = await flare.Row(button)

        await ctx.app.rest.create_message(config.channel, self.content, component=row)

        await ctx.respond("Done.")

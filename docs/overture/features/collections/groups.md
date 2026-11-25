---
sidebar_position: 4
title: Groups
description: Shared settings, defaults, separators and what happens when a group goes.
---

# Groups

Every collection Overture manages belongs to a group, which you choose or name
when you create or adopt it. The sidebar's **Groups** view organises collections
by these groups, and lists the server collections Overture does not manage under
**Unmanaged**. Movies and shows share groups.

## A group's page

Click a group in the sidebar to open it: the sidebar lists its collections,
and the group's page opens beside it. On a phone the sidebar stays in front;
tap the group's name at the top of the list to open its page.

A group's page is laid out as a collection's is:

1. **Setup**: its name, which **Rename** changes; for a set, what it splits
   by, its title template and its libraries.
2. **Content**: for a set only, what it makes a collection for, and
   **Stop creating collections**, which, once saved, leaves its collections in
   the group as they are and stops the set making and updating them.
3. **Members**: the collections in the group, each opening its own page.
4. **Settings** and **Active dates**: the defaults its collections inherit.

**Save** saves the group in Overture at once; its collections get its display
settings on the server with their next sync, keeping members and explicit
overrides. **Save and Sync** saves, then opens **Sync** in Operations with
only this group chosen, which runs the set and syncs the group's collections.

A group is made by naming it: type a new name in a collection's **Group**, in
**Adopt**, or in **Assign group** among the collection operations, or create a
set with **Create → One per value**, which is also how a group that holds
collections becomes a set. `Unmanaged`, which gathers the collections Overture
does not manage, has no page and cannot name a group. Sync and Assets schedules, and the groups the Sync and Assets tabs
remember, keep a renamed group chosen.

## Defaults

A group's settings on its page and the global defaults under
**Settings > Collections** use the same fields and names. **Default**
inherits, from the group and then the global default, and names the value it
inherits.

A group can hold regular and smart collections; a custom order applies to its
regular ones only. A smart collection never takes a group's **Custom** order,
which Plex cannot apply to it; it takes the next order the settings give.

## Separators

**Separator**, a Plex setting on a group's page, heads the group
with an empty collection titled after it, with a poster generated in the group's
Generated colours and showing the group's name alone, in each library its
collections use. Its sort title is the group's sort title template with an
empty title, so it sorts right before the group's collections. A separated
group whose sort title is not set anywhere sorts its collections as
`{group} {title}`, which keeps them together behind it. Sort titles leave out
a leading "The", "A" or "An" of the title and group, as Plex does when it
sorts titles itself, so _The Matrix_ in _The Sagas_ sorts as `Sagas Matrix`.

The group keeps it, and the group's next sync makes it as the group says:
renaming the group renames it, turning the setting off or deleting the group
removes it. It is not listed among the collections in the sidebar or
Collection operations; its group's settings are where it is kept. Separators
are offered on Plex only, the one server whose empty collections Overture has
checked.

## Deleting a group

**Delete group**, the trash icon on the group's page, asks what happens to its
collections: move them to another group, orphan them (Overture stops managing
them and the server keeps them, listed under Unmanaged), or delete them from
both Overture and the server. A group without collections is deleted once you
confirm.

Bulk group assignment offers the existing groups.

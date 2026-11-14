---
sidebar_position: 4
title: Groups
description: Shared settings, defaults, separators and what happens when a group goes.
---

# Groups

Every managed collection belongs to a group; missing membership uses
**Ungrouped**. The sidebar's **Groups** view organises collections by these
groups and keeps unmanaged server collections separate. Movies and shows share
groups.

## Collection groups

**Collection groups**, opened from **Manage groups** in the collection sidebar
or **Create new group** in Setup's Group list, creates groups and edits a
group's collection set, Settings and Active dates; Setup only assigns a group.

**Save** saves the group in Overture at once; its collections get its display
settings on the server with their next sync, keeping members and explicit
overrides. **Save and Sync** saves, then opens **Sync** in Operations with
only this group chosen, which runs the set and syncs the group's collections;
the group needs a collection or a set first.

Rename or delete a custom group in **Collection groups**. Ungrouped cannot be
renamed, deleted or made a collection set, and `Unmanaged` cannot name a
custom group.

## Defaults

A group's settings in **Collection groups** and the global defaults under
**Settings > Collections** use the same fields and names. **Default**
inherits, from the group and then the global default, and names the value it
inherits.

A group can hold regular and smart collections; a custom order applies to its
regular ones only. A smart collection never takes a group's **Custom** order,
which Plex cannot apply to it; it takes the next order the settings give.

## Separators

**Separator**, a Plex group setting in **Collection groups**, heads the group
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

Deleting a group moves its collections to the reserved **Ungrouped** group by
default; you can instead move them to another group, orphan them (Overture
stops managing them and the server keeps them, listed under Unmanaged), or
delete them from both Overture and the server; **Delete group** asks which.

Bulk group assignment offers the existing groups.

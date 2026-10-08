"""The apps the index follows. Each sells its plans through the App Store, so every country's store page lists them.

`headline` picks the plan the maps and rankings use (a regex on the English plan name, monthly price). Leave it None to let the
build choose the plan sold in the most countries. Netflix and Spotify don't sell plans inside their iPhone apps, so they aren't here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class App:
    slug: str
    name: str
    id: int
    category: str
    headline: str | None = None
    daily: bool = False  # collected every day; the others once a week


APPS: tuple[App, ...] = (
    # AI assistants: collected daily
    App("chatgpt", "ChatGPT", 6448311069, "AI assistants", r"^ChatGPT Plus$", daily=True),
    App("claude", "Claude", 6473753684, "AI assistants", r"\bPro\b", daily=True),
    App("gemini", "Google Gemini", 6477489729, "AI assistants", r"AI Pro|Advanced|Premium", daily=True),
    App("perplexity", "Perplexity", 1668000334, "AI assistants", r"Pro", daily=True),
    App("grok", "Grok", 6670324846, "AI assistants", r"^SuperGrok$", daily=True),
    App("copilot", "Microsoft Copilot", 541164041, "AI assistants", r"Copilot Pro|365 Premium|Personal", daily=True),
    App("le-chat", "Le Chat (Vibe by Mistral)", 6740410176, "AI assistants", r"Pro", daily=True),
    App("character-ai", "Character.AI", 1671705818, "AI assistants", r"c\.ai\+|\+", daily=True),
    # Video and music
    App("youtube", "YouTube Premium", 544007664, "Video and music", r"^YouTube Premium$"),
    App("disney-plus", "Disney+", 1446075923, "Video and music"),
    App("hbo-max", "HBO Max", 1666653815, "Video and music"),
    App("crunchyroll", "Crunchyroll", 329913454, "Video and music"),
    # Social and chat
    App("telegram", "Telegram Premium", 686449807, "Social and chat", r"Premium"),
    App("snapchat", "Snapchat+", 447188370, "Social and chat", r"Snapchat\+|Platinum"),
    App("x", "X Premium", 333903271, "Social and chat", r"^Premium$|Premium \(Monthly\)"),
    App("discord", "Discord Nitro", 985746746, "Social and chat", r"^Nitro\b"),
    App("linkedin", "LinkedIn Premium", 288429040, "Social and chat", r"Career"),
    App("tinder", "Tinder", 547702041, "Social and chat", r"Gold"),
    App("bumble", "Bumble", 930441707, "Social and chat"),
    # Learning, creating, health, privacy, storage, work
    App("duolingo", "Duolingo", 570060128, "Learning and work", r"Super"),
    App("notion", "Notion", 1232780281, "Learning and work"),
    App("canva", "Canva", 897446215, "Creative", r"Canva Pro"),
    App("capcut", "CapCut", 1500855883, "Creative", r"Pro"),
    App("strava", "Strava", 426826309, "Health and fitness"),
    App("calm", "Calm", 571800810, "Health and fitness"),
    App("headspace", "Headspace", 493145008, "Health and fitness"),
    App("nordvpn", "NordVPN", 905953485, "Privacy and storage"),
    App("expressvpn", "ExpressVPN", 886492891, "Privacy and storage"),
    App("google-one", "Google One", 1451784328, "Privacy and storage"),
)

BY_SLUG = {a.slug: a for a in APPS}

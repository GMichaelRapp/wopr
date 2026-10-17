# WOPR

WOPR is a personal news page that pulls from about 190 sources: wire services, think tanks, defense and naval outlets, cyber, terrorism research, Substacks, and Google News topic searches. It's grouped into beats you can filter. GitHub rebuilds it every three hours and hosts it free on GitHub Pages.

Each story is a card: the **headline on top**, its **link directly below** (site in bold, then the path, plus a Copy button for citations), and the source, beat and time underneath.

## Set it up (about 10 minutes, once)

1. **Create a repository** on GitHub, for example `wopr`. Make it **public**: Actions and Pages are free there. GitHub Pages on a private repo needs a paid plan.
2. **Upload these files**, keeping the folder structure, including the hidden `.github/workflows/build.yml`. The easiest way is from a computer: on the new repo's page choose *uploading an existing file* and drag the whole folder in.
3. **Settings → Pages →** under *Build and deployment*, set **Source** to **GitHub Actions**.
4. **Settings → Actions → General →** under *Workflow permissions*, choose **Read and write permissions** and save.
5. **Actions tab → Build WOPR → Run workflow.** The first run takes a minute or two.
6. Your page is at `https://YOUR-USERNAME.github.io/wopr/`. Bookmark it, or add it to your phone's home screen.

After that it runs on its own every three hours, and again whenever you edit `feeds.yaml`.

## Change the sources

Edit **`feeds.yaml`**. You can do this in the GitHub mobile app or on the website with the pencil icon. Each beat is a list, and an entry is one of:

```yaml
- {name: Krebs on Security, url: https://krebsonsecurity.com/feed/}   # the site's own feed
- {name: CSIS, site: csis.org}                                        # a site with no feed (via Google News)
- '"Taiwan Strait"'                                                    # any Google News search
```

If a URL contains a `?`, put it in quotes: `url: "https://example.com/rss/?format=xml"`.

New beats appear on the page automatically. Optional extras on an entry: `include: [drone, missile]` keeps only matching stories, and `enabled: false` switches a source off.

**Finding feeds:** Substack is `https://NAME.substack.com/feed`. YouTube is `https://www.youtube.com/feeds/videos.xml?channel_id=UC…`, and the channel ID is in the channel's share link or page source. Most WordPress sites use `/feed/`. Reddit is `/r/NAME/.rss`.

## Add a source from the page

Tap **+ Source** at the top of the page. Choose one of:
- **a website or feed:** paste any site's address. You don't need to hunt for its RSS link, because the build finds the feed a page advertises. Substack and Reddit links are converted for you.
- **a site with no feed:** give its domain, and it's pulled through Google News.
- **a Google News search:** any search you'd type into Google News.

Pick a beat, or make a new one. You can also add citation details, which are the same `location`, `desc` and `access` used in `feeds.yaml`.

Then tap **Add on GitHub**. GitHub opens with a small file for the new source already written into the `sources` folder. Tap **Commit changes**, sign in if asked, and the feed rebuilds with the source a few minutes later.

The form warns you if a source is already in the feed. Afterwards, **source status** shows whether the new source worked, and the feed address it found.

To remove or move an added source, delete or edit its file in `sources/`. Sources in `feeds.yaml` and in `sources/` work the same way, so you can also paste the YAML the form shows (**Copy YAML**) straight into `feeds.yaml` if you'd rather keep everything in one file.

## OSINT citations

Every story has a **Cite** button. It shows the story's footnote in OSINT Style Guide form, with a button to copy it. The copy keeps italics when you paste into Word, Google Docs or Substack, and uses *asterisks* in plain text.

The footnotes come from the OSINT Cites formatter itself, not a re-creation of it. Each build fetches the current formatter from the generator, and `vendor/osint-core.js` is a saved copy used if the generator can't be reached. A change to the generator therefore carries through to WOPR on its next run.

A feed only supplies some of a footnote: the title, link, date and usually an author. The rest comes from each source's entry in `feeds.yaml` (see the comments at its top):
- `location`
- `desc` (the kind of source for the bracket)
- `access` (paywall notes)
- `publisher`
- `author` (an organization, used when the feed names no one)

Ratings are never filled in. They stay your call.

**Edit** opens every slot of the footnote:
- the opening (See, Cited in, Quoted in)
- authors, title and title style
- publication and kind of source
- details, qualifiers and access
- your rating
- publisher and date
- link and archive copy
- locator and commentary

The footnote updates as you type. Edits are saved in that browser, so they also appear in your list, Print / PDF, *Copy all citations* and the OSINT Cites export. **Reset to feed data** undoes them. **Copy citation** copies the full footnote, and **Copy short form** copies the short form for citing the same source again.

Under each footnote, the page lists anything the feed couldn't settle:
- **No byline in the feed:** add the author from the story.
- **No date in the feed:** take the publication date from the story.
- **Kind of source left at its default:** check that it fits this story.
- **Google News redirect:** stories found through Google News only come with a redirect link, so the footnote leaves the URL out until you add the publisher's own link.
- **The generator's own checks:** for example, a Reddit post with no archive copy.

## Source list and Print / PDF

- **+ List** on any story adds it to your source list, which is kept in that browser.
- **View list** opens the list. There you can name the piece, reorder or remove stories, and then:
  - **Print / PDF:** a clean printout of the list, numbered, with each headline, its full link and, if ticked, its OSINT citation. Choose *Save as PDF* in the print dialog. On an iPhone, use Print, then the Share button on the preview.
  - **Copy all citations:** all footnotes, numbered, including your edits.
  - **Export for OSINT Cites:** a list file in the generator's own format. Open it in OSINT Cites with **Open a list file**, then run **Audit the list** before publishing. The export was tested against the generator's own file reader and produced identical footnotes.
- **Print / PDF** at the top of the feed prints whatever is showing, so pick a beat or type a filter first. Any citations you have opened print along with their stories.

## Check what's working

The page header links to **source status** (`status.html`), which lists every source from the last run with failures first. The source list was compiled from each site's usual feed address, and not every address has been tested, so expect some failures on the first run. When a source keeps failing:
- fix its address,
- swap `url:` for `site: thedomain.com` so it comes through Google News, or
- delete it.

Each run's summary on the Actions tab lists the same failures.

## What else it produces

- `feed.xml`: everything on the page as one combined RSS feed. You can subscribe to it in any reader or use it as a single input for other tools.
- `feed.json`: the same in JSON.
- `data/items.json`: a rolling 30-day archive saved in the repo. Stories stay findable after they drop off the source feeds. The archive commit also keeps the repo "active," which matters because GitHub pauses scheduled workflows on repos with no activity for 60 days.

## Settings

The top of `feeds.yaml` controls:
- `page_hours`: how far back the page reaches (default 72).
- `archive_days`: how long the archive keeps stories.
- `exclude`: words that drop a headline everywhere.
- `timezone`: the time zone used for times on the page.
- To change how often it runs, edit the `cron` line in `.github/workflows/build.yml`. It is in UTC, and runs can start 10–30 minutes late when GitHub is busy.

## Run it on your own computer

```
pip install -r requirements.txt
python build.py
```

Then open `docs/index.html`.

## Notes

- **Duplicates:** the same story is merged when it arrives from several outlets with the same headline. The card shows "also: AP News, Reuters" so you can see how widely it's being reported.
- **Google News links** open through a Google redirect. The card shows the publisher's site name so you know where it leads.
- **Reddit** often blocks GitHub's servers. If those three sources fail, set them to `enabled: false`.

from __future__ import annotations

from pathlib import Path

OUTPUT_DIR = Path("backend/scripts/catalogs/output")


def generate_about_topspot40_page() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    page = """<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>About TopSpot40</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 32px auto;
            max-width: 1000px;
            padding: 0 24px;
        }

        .nav {
            margin-bottom: 24px;
            font-size: 15px;
        }

        .nav a {
            color: #0645ad;
            text-decoration: none;
            margin-right: 14px;
        }

        h1 {
            font-size: 46px;
            margin-bottom: 8px;
            text-transform: uppercase;
        }

        .subtitle {
            font-size: 20px;
            line-height: 1.4;
            color: #555;
            margin-bottom: 30px;
        }

        h2 {
            font-size: 28px;
            margin-top: 30px;
            border-top: 1px solid #ccc;
            padding-top: 18px;
        }

        p {
            font-size: 17px;
            line-height: 1.5;
        }

        .quote {
            margin: 22px 0;
            padding: 14px 18px;
            background: #f4f4f4;
            border-left: 4px solid #777;
            font-size: 18px;
            line-height: 1.45;
            font-style: italic;
        }

        .note {
            margin: 22px 0;
            padding: 14px 18px;
            background: #f8f8f8;
            border-left: 4px solid #2c7be5;
            font-size: 16px;
            line-height: 1.45;
        }

        .footer {
            margin-top: 40px;
            border-top: 1px solid #ccc;
            padding-top: 14px;
            color: #555;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="nav">
        <a href="index.html">TopSpot40 Catalog</a>
    </div>

    <h1>About TopSpot40</h1>

    <div class="subtitle">
        Why I created TopSpot40, and why music discovery still matters.
    </div>

    <h2>Growing Up with Radio</h2>
    <p>
        TopSpot40 began with memories of growing up on an Indiana farm, where radio was more
        than background noise. Programs like Casey Kasem's American Top 40 did more than play
        songs. They created anticipation, told stories, introduced artists, and made music feel
        like a journey.
    </p>

        <h2>The Story Behind the Name</h2>
    <p>
        People occasionally ask where the name <strong>TopSpot40</strong> came from.
        The answer reflects the three major influences behind the project.
    </p>

    <p>
        The word <strong>Top</strong> refers to the ranked music programs that form
        the foundation of TopSpot40. Like the countdown shows I enjoyed growing up,
        songs are organized into ranked lists that highlight memorable tracks from
        each decade, genre, or collection.
    </p>

    <p>
        The word <strong>Spot</strong> is a nod to Spotify, the music streaming platform
        that TopSpot40 integrates with for music playback. TopSpot40 focuses on music
        discovery, rankings, artist biographies, storytelling, and historical context,
        while Spotify provides the licensed music streaming experience.
    </p>

    <p>
        The number <strong>40</strong> comes from the influence of Casey Kasem's
        American Top 40 countdowns. Those programs inspired my love of music rankings,
        artist stories, and the excitement of discovering what song would come next.
    </p>

    <p>
        Put together, the name <strong>TopSpot40</strong> represents ranked music
        discovery, Spotify-integrated listening, and the enduring influence of the Top 40
        radio tradition that inspired the project.
    </p>

    <p>
        I wanted to bring some of that feeling back. Streaming services make it easy to hear
        almost any song instantly, but the stories behind the songs are often missing.
        TopSpot40 was created to add the context, history, artist information, and storytelling
        that make music more meaningful.
    </p>

    <h2>Music, Memory, and Older Generations</h2>
    <p>
        One of my hopes for TopSpot40 is that it can help older generations reconnect with the
        songs that shaped their lives. A favorite song can bring back memories of childhood,
        first dates, military service, weddings, family gatherings, church, road trips, and
        moments that might otherwise have faded.
    </p>

    <p>
        Music has a special ability to connect people across generations. TopSpot40 is my way
        of honoring those memories while helping younger listeners discover the music, artists,
        and stories that came before them.
    </p>

<h2>Patty's Rule</h2>

<p>
My wife Patty has played an important role in shaping TopSpot40 from the very beginning. Fluent in English, Spanish, and Portuguese, she brought a unique perspective to the project as both a music lover and a multilingual listener.
</p>

<p>
Over time, I developed what I jokingly call "Patty's Rule": if Patty cannot easily understand or enjoy a feature, it probably needs to be simplified. That simple principle helped keep TopSpot40 focused on the listener rather than the technology. As an engineer, I naturally enjoy building systems and adding features, but Patty consistently reminded me that the experience should remain intuitive, enjoyable, and accessible.
</p>

<p>
Patty also played a vital role in one of the most distinctive parts of TopSpot40—its narrated storytelling. As we explored the growing library of ElevenLabs voices, she helped evaluate and select many of the voices used throughout the platform. Her fluency in all three supported languages allowed her to judge pronunciation, pacing, tone, and overall authenticity in ways that I could not have done alone.
</p>

<p>
The result is that TopSpot40 does not simply tell stories in English, Spanish, and Portuguese—it tells them in voices carefully chosen to sound natural and engaging to listeners in each language. Many of the voices heard throughout the platform were selected with Patty's guidance and encouragement.
</p>

<p>
In many ways, Patty helped shape not only how TopSpot40 works, but also how it sounds.
</p>

<div class="quote">
Patty's Rule: If a feature is too complicated to enjoy, it probably needs to be simplified.
</div>


    <h2>Teaching, Isaiah, and the Python Class</h2>
    <p>
        TopSpot40 also grew out of my work with the Pharr Fetched Coders group at the Pharr
        Memorial Library. What started as a local Python programming class became connected to
        a real software project.
    </p>

    <p>
        Through that group, I met Isaiah, a computer science student at the University of Texas
        Rio Grande Valley. Working with him reminded me that learning is a two-way street. I
        have been able to share decades of experience in programming, engineering, and project
        development, while Isaiah has brought fresh ideas, modern web development skills, and
        a new perspective to the platform.
    </p>

    <h2>Music Without Borders</h2>
    <p>
        My life and career have also shaped the multilingual side of TopSpot40. I am bilingual
        in English and Spanish, and somewhat fluent in Portuguese after working in Angola, Africa
        as a Six Sigma consultant. Those experiences expanded my appreciation for the ways music
        connects people across languages and cultures.
    </p>

    <p>
        That is one reason TopSpot40 supports English, Spanish, and Portuguese. Music may be a
        universal language, but I wanted the stories behind the music to be accessible too.
    </p>

    <h2>A Personal Journey</h2>
    <p>
        What began as a software project gradually became something much more personal. Along
        the way, TopSpot40 introduced me to artists, stories, cultures, and musical traditions
        that I might never have explored otherwise.
    </p>

    <p>
        In that sense, TopSpot40 has been almost a spiritual journey for me. It has deepened my
        appreciation for music, history, heritage, creativity, and the experiences that connect
        us across generations.
    </p>

    <div class="quote">
        TopSpot40 is not designed to help people listen to more music.
        It is designed to help people connect more deeply with the music they already love.
    </div>

    <h2>Discovery Never Ends</h2>
    <p>
        One of my favorite discoveries came from my own project. While exploring music and
        artists for TopSpot40, I came across B.B. King and realized I knew very little about him,
        despite his enormous influence on blues and popular music.
    </p>

    <p>
        That discovery led me to learn about his remarkable career, his influence on generations
        of musicians, and his connection to artists such as Buddy Guy. In fact, learning through
        TopSpot40 inspired me to plan a trip to see Buddy Guy perform in person.
    </p>

    <p>
        If TopSpot40 has taught me anything, it is that discovery never ends. There is always
        another artist to learn about, another story to hear, another culture to appreciate,
        and another song waiting to become a favorite.
    </p>

    <h2>Spotify Integration</h2>

    <p>
        TopSpot40 is a music discovery and storytelling platform that integrates with
        Spotify for music playback. TopSpot40 does not host, distribute, or provide
        music files. Instead, it enhances the listening experience through rankings,
        artist biographies, narrated stories, music history, and curated listening
        programs.
    </p>


    <div class="note">
        Spotify provides the licensed music streaming experience. TopSpot40 provides
        the stories, rankings, historical context, artist biographies, and discovery
        features that help listeners connect more deeply with the music.
    </div>

    <div class="footer">
        TopSpot40.com — Music Discovery Through the Decades
    </div>
</body>
</html>
"""

    output_path = OUTPUT_DIR / "about_topspot40.html"
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    output_path = generate_about_topspot40_page()
    print(f"Created: {output_path}")


if __name__ == "__main__":
    main()

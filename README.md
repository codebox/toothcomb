Toothcomb is an AI-powered tool for analysing and fact-checking speech in real time.

It is much easier to make claims than to verify them. In this sense, a speaker has a big advantage over their audience. A clever orator can deceive and distract us with a little charisma and a bag of rhetorical tricks. Toothcomb doesn't care who is talking or how persuasive they seem, it checks everything that is said and calls out all the bullshit.

[![Toothcomb analysing Trump's Davos 2026 speech](https://codebox.net/assets/video/toothcomb/trump_davos_2026_poster.png)](https://codebox.net/assets/video/toothcomb/trump_davos_2026.mp4)

Give Toothcomb a speech transcript and it will fact-check and analyse it. If you have an MP3 file of someone speaking, it can generate the transcript for you. You can also stream audio in real time from your device's microphone.

Analysis is performed in three stages:

1. The text is broken up into small parts referred to as 'utterances'. Each utterance is usually a few sentences in length. The utterances are sent, one at a time, to a powerful AI language model with [detailed instructions about what to look for](https://github.com/codebox/toothcomb/blob/main/resources/prompts/utterance_analysis.txt). The AI will respond with a list of what it found - this may include claims, promises or predictions made by the speaker, logical fallacies, and deceptive or manipulative language.
2. The AI may decide that some of the speaker's statements require fact-checking. It may be able to perform these checks using what it already knows, or it may need to search the web to get up-to-date information.
3. Once each part of the speech has been checked separately, a [final review of the entire speech is performed](https://github.com/codebox/toothcomb/blob/main/resources/prompts/transcript_review.txt). The final review can pick up things that aren't apparent from looking at small parts in isolation. For example, it will check if the speaker contradicts themselves, or promises to address some issue and then fails to do so.

When you create a new transcript in Toothcomb you will be prompted to enter various details about the speech, such as the date/time the speech was made, who was speaking, and where the speech took place. You can also enter background information to place the speech and the speaker in context. Entering full and accurate details here will improve the results of the analysis.

For example, without context it's impossible to tell if a quote like this can be falsified:

> Before I even arrive at the Oval Office, shortly after I win the presidency, I will have the horrible war between Russia and Ukraine settled.

However if you let Toothcomb know Donald Trump said that on 26th August 2024, then it's clear it did not in fact happen, and that the claim was false.

The usual caveats apply - AI systems make mistakes and can hallucinate. Toothcomb will often cite sources that support its conclusions, but you should still check anything important yourself. Any data you enter into Toothcomb will be sent to Anthropic so use your judgement about what is safe to enter. You can read their [data handling policies](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data) to inform your decision.

Toothcomb stores its data in a local SQLite database on your machine. The only data that is sent to Anthropic is the text of the speeches you analyse, and the results of the analysis. If you use the transcription feature, then the audio of the speech will be processed locally on your machine by a speech-to-text model, and only the resulting transcript will be sent to Anthropic.

You can [try out the Toothcomb demo](https://toothcomb.codebox.net/) for yourself, and review the results of some analyses that I've already done.

- It has a lot to say about [this sentence](https://toothcomb.codebox.net/#c4cbe6a9-2856-4167-9b41-ec2d0e9f1c65/3) from Donald Trump's speech at Davos 2026, and [this one](https://toothcomb.codebox.net/#c4cbe6a9-2856-4167-9b41-ec2d0e9f1c65/84), aaand [this one](https://toothcomb.codebox.net/#c4cbe6a9-2856-4167-9b41-ec2d0e9f1c65/98)...
- It debunks some [flat-earth conspiracy theories](https://toothcomb.codebox.net/#926e299a-18cd-4434-94ac-a90e3a859639/50)
- Calls out [flawed 'race realism' arguments](https://toothcomb.codebox.net/#e8ce11e8-3459-4d6f-a95f-e94ebdba0629/68)
- Picks apart [Jim Carrey's poorly informed article about vaccination](https://toothcomb.codebox.net/#1ad5a20d-81af-4aef-aa0f-e102c86e5b16/116)
- Points out that Vanilla Ice does not, in fact, have a ['brand new invention'](https://toothcomb.codebox.net/#bcd3f446-6733-4f21-86f8-0ec70daef70c/1).
- And slowly shakes its head and sighs [when David Icke talks about COVID-19](https://toothcomb.codebox.net/#30cc41e0-fc91-4158-af30-77dc11a55ae0/21).

### Running Toothcomb

You can run Toothcomb natively on macOS or Linux, and via Docker on many platforms. The transcription feature works best with access to a GPU. You will also need an [Anthropic API key](https://platform.claude.com/docs/en/home) which must be saved in a file called `.env` in the root of the project, like this:

```
LLM__ANTHROPIC__API_KEY=your-key-goes-here
```

The code requires at least Python 3.12 and Node.js v22. If you run the application using Docker these will be installed automatically within the container, but if you run it natively on your machine you'll need to install them yourself.

The first time you run it, Toothcomb will probably need to download a [Whisper speech-to-text model](https://github.com/openai/whisper/blob/main/model-card.md) which is several gigabytes in size. The app will not be ready to use until the download completes. Subsequent runs use the cached model and start up much faster. Models are cached in `~/.cache/huggingface/hub/` and are shared across projects, so you only download each model once per machine.

Once Toothcomb is up and running you can access the web interface at [http://localhost:5000](http://localhost:5000).

<details>
<summary>macOS (Apple Silicon)</summary>

Running natively (i.e. outside Docker) is recommended on Apple Silicon Macs. At the time of writing Docker on macOS cannot access the Apple GPU, so it would fall back to CPU-only mode and the transcription would run very slowly.

Running the following command from the root of the project will create a Python virtual environment, pull in all the dependencies, compile the TypeScript frontend and start the server.

```
make run
```

If for some reason you wish to use Docker just run this command from the root of the project:

```
docker compose --profile cpu up --build
```

</details>

<details>
<summary>Linux</summary>

If you have an NVIDIA GPU, and have the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed, then you can run the following command from the root of the project to start Toothcomb in GPU mode:

```
docker compose --profile gpu up --build
```

To run in CPU-only mode use this command instead:

```
docker compose --profile cpu up --build
```

To run Toothcomb outside of Docker use the following command from the root of the project. This will create a Python virtual environment, pull in all the dependencies, compile the TypeScript frontend and start the server. This will install the [Faster Whisper library](https://github.com/SYSTRAN/faster-whisper) which will automatically use your GPU if it's available.

```
make run
```

</details>

<details>
<summary>Windows (untested)</summary>

Probably the best way to run Toothcomb on Windows is to install [Windows Subsystem for Linux](https://learn.microsoft.com/en-us/windows/wsl/install), and then follow the Linux instructions above. If you have an NVIDIA GPU, install the CUDA drivers for WSL and use the GPU Docker profile.

</details>

#### Performance

On a modern device with a GPU the transcription and most of the LLM analysis will run more or less in real time. By far the slowest part of the process is performing the fact checks that require web searches. For long speeches containing many claims, this can result in a lengthy backlog of pending verification requests. You can significantly speed this up by increasing the `fact_check_workers` value [in the configuration file](https://github.com/codebox/toothcomb/blob/main/resources/config.yaml#L105), allowing multiple fact checks to run concurrently. Depending on what [Usage Tier](https://platform.claude.com/docs/en/api/rate-limits#spend-limits) is assigned to your Anthropic account, this may result in your queries being rate limited.

### AI Disclosure

The architecture and high-level design of both the code and the user interface were created by me; most of the actual code was written by Claude Code/Opus 4.6. During development I micro-managed Claude to the point where any human developer would have resigned, and been right to do so. This felt like a genuine collaboration, and the resulting code is probably as good as if I'd written it by hand myself, but it took a lot less time to finish.
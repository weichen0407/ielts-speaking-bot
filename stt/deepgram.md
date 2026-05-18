---
title: Getting Started
subtitle: >-
  An introduction to getting transcription data from live streaming audio in
  real time.
slug: docs/live-streaming-audio
---

<Card
    href="https://playground.deepgram.com/?endpoint=listen-streaming&language=en&model=nova-3"
>
  <div class="t-default text-base font-semibold">Deepgram API Playground</div>
  Try this feature out in our API Playground.
</Card>

In this guide, you'll learn how to automatically transcribe live streaming audio in real time using Deepgram's SDKs, which are supported for use with the [Deepgram API](/reference/deepgram-api-overview). (If you prefer not to use a Deepgram SDK, jump to the section [Non-SDK Code Examples](/docs/live-streaming-audio#non-sdk-code-examples).)

<Info>
  Before you start, you'll need to follow the steps in the [Make Your First API Request](/guides/fundamentals/make-your-first-api-request) guide to obtain a Deepgram API key, and configure your environment if you are choosing to use a Deepgram SDK.
</Info>

## SDKs

To transcribe audio from an audio stream using one of Deepgram's SDKs, follow these steps.

### Install the SDK

Open your terminal, navigate to the location on your drive where you want to create your project, and install the Deepgram SDK.

<CodeGroup>
  ```JavaScript
  // Install the Deepgram JS SDK
  // https://github.com/deepgram/deepgram-js-sdk

  // npm install @deepgram/sdk
  ```

  ```Python
  # Install the Deepgram Python SDK
  # https://github.com/deepgram/deepgram-python-sdk

  # pip install deepgram-sdk
  ```

  ```csharp C#
  // Install the Deepgram .NET SDK
  // https://github.com/deepgram/deepgram-dotnet-sdk

  // dotnet add package Deepgram
  ```

  ```Go
  // Install the Deepgram Go SDK
  // https://github.com/deepgram/deepgram-go-sdk

  // go get github.com/deepgram/deepgram-go-sdk
  ```

  ```java Java
  // Install the Deepgram Java SDK
  // https://github.com/deepgram/deepgram-java-sdk

  // Maven — add to pom.xml:
  // <dependency>
  //   <groupId>com.deepgram</groupId>
  //   <artifactId>deepgram-java-sdk</artifactId>
  //   <version>0.2.1</version>
  // </dependency>

  // Gradle — add to build.gradle:
  // implementation 'com.deepgram:deepgram-java-sdk:0.2.1'
  ```
</CodeGroup>

### Add Dependencies

<CodeGroup>
  ```JavaScript
  // Install cross-fetch: Platform-agnostic Fetch API with typescript support, a simple interface, and optional polyfill.
  // Install dotenv to protect your api key

  // $ npm install cross-fetch dotenv
  ```

  ```Python
  # Install httpx to make http requests

  # pip install httpx
  ```

  ```csharp C#
  // In your .csproj file, add the Package Reference:

  // <ItemGroup>
  //     <PackageReference Include="Deepgram" Version="4.4.0" />
  // </ItemGroup>
  ```

  ```Go
  // Importing the Deepgram Go SDK should pull in all dependencies required
  ```
</CodeGroup>

### Transcribe Audio from a Remote Stream

The following code shows how to transcribe audio from a remote audio stream.

<CodeGroup>
  ```javascript JavaScript
  // Example filename: index.js

  const { DeepgramClient } = require("@deepgram/sdk");
  const fetch = require("cross-fetch");
  const dotenv = require("dotenv");
  dotenv.config();

  // URL for the realtime streaming audio you would like to transcribe
  const url = "http://stream.live.vc.bbcmedia.co.uk/bbc_world_service";

  const live = async () => {
    // STEP 1: Create a Deepgram client using the API key
    const deepgram = new DeepgramClient({ apiKey: process.env.DEEPGRAM_API_KEY });

    // STEP 2: Create a live transcription connection
    const connection = await deepgram.listen.v1.connect({
      model: "nova-3",
      language: "en-US",
      smart_format: "true",
    });

    // STEP 3: Listen for events from the live transcription connection
    connection.on("open", () => {
      connection.on("close", () => {
        console.log("Connection closed.");
      });

      connection.on("message", (data) => {
        if (data.type === "Results") {
          console.log(data.channel.alternatives[0].transcript);
        }
      });

      connection.on("error", (err) => {
        console.error(err);
      });

      // STEP 4: Fetch the audio stream and send it to the live transcription connection
      fetch(url)
        .then((r) => r.body)
        .then((res) => {
          res.on("readable", () => {
            connection.sendMedia(res.read());
          });
        });
    });

    connection.connect();
    await connection.waitForOpen();
  };

  live();
  ```

  ```python Python
  # Example filename: main.py

  # For more Python SDK migration guides, visit:
  # https://github.com/deepgram/deepgram-python-sdk/tree/main/docs

  # Set your Deepgram API key as an environment variable:
  # export DEEPGRAM_API_KEY="your-api-key-here"

  import httpx
  import logging
  import threading

  from deepgram import (
      DeepgramClient,
  )
  from deepgram.core.events import EventType

  # URL for the realtime streaming audio you would like to transcribe
  URL = "http://stream.live.vc.bbcmedia.co.uk/bbc_world_service"

  def main():
      try:
          # use default config
          deepgram: DeepgramClient = DeepgramClient()

          # Create a websocket connection to Deepgram
          with deepgram.listen.v1.connect(model="nova-3") as connection:
              def on_message(message) -> None:
                  msg_type = getattr(message, "type", "Unknown")
                  if hasattr(message, 'channel') and hasattr(message.channel, 'alternatives'):
                      sentence = message.channel.alternatives[0].transcript
                      if len(sentence) == 0:
                          return
                      print(message.channel.json(indent=4))

              connection.on(EventType.OPEN, lambda _: print("Connection opened"))
              connection.on(EventType.MESSAGE, on_message)
              connection.on(EventType.CLOSE, lambda _: print("Connection closed"))
              connection.on(EventType.ERROR, lambda error: print(f"Error: {error}"))

              lock_exit = threading.Lock()
              exit = False

              # Define a thread for start_listening with error handling
              def listening_thread():
                  try:
                      connection.start_listening()
                  except Exception as e:
                      print(f"Error in listening thread: {e}")

              # Start listening in a separate thread
              listen_thread = threading.Thread(target=listening_thread)
              listen_thread.start()

              # define a worker thread for HTTP streaming with error handling
              def myThread():
                  try:
                      with httpx.stream("GET", URL) as r:
                          for data in r.iter_bytes():
                              lock_exit.acquire()
                              if exit:
                                  break
                              lock_exit.release()

                              connection.send_media(data)
                  except Exception as e:
                      print(f"Error in HTTP streaming thread: {e}")

              # start the HTTP streaming thread
              myHttp = threading.Thread(target=myThread)
              myHttp.start()

              # signal finished
              input("")
              lock_exit.acquire()
              exit = True
              lock_exit.release()

              # Wait for both threads to close and join with timeout
              myHttp.join(timeout=5.0)
              listen_thread.join(timeout=5.0)

              print("Finished")

      except Exception as e:
          print(f"Could not open socket: {e}")
          return

  if __name__ == "__main__":
      main()
  ```

  ```csharp C#
  // Example filename: Program.cs

  using Deepgram.Models.Listen.v2.WebSocket;

  namespace SampleApp
  {
      class Program
      {
          static async Task Main(string[] args)
          {
              try
              {
                  // Initialize Library with default logging
                  Library.Initialize();

                  // use the client factory with a API Key set with the "DEEPGRAM_API_KEY" environment variable
                  var liveClient = new ListenWebSocketClient();

                  // Subscribe to the EventResponseReceived event
                  await liveClient.Subscribe(new EventHandler<ResultResponse>((sender, e) =>
                  {
                      if (e.Channel.Alternatives[0].Transcript == "")
                      {
                          return;
                      }
                      Console.WriteLine($"Speaker: {e.Channel.Alternatives[0].Transcript}");
                  }));

                  // Start the connection
                  var liveSchema = new LiveSchema()
                  {
                      Model = "nova-3",
                      SmartFormat = true,
                  };
                  bool bConnected = await liveClient.Connect(liveSchema);
                  if (!bConnected)
                  {
                      Console.WriteLine("Failed to connect to the server");
                      return;
                  }

                  // get the webcast data... this is a blocking operation
                  try
                  {
                      var url = "http://stream.live.vc.bbcmedia.co.uk/bbc_world_service";
                      using (HttpClient client = new HttpClient())
                      {
                          using (Stream receiveStream = await client.GetStreamAsync(url))
                          {
                              while (liveClient.IsConnected())
                              {
                                  byte[] buffer = new byte[2048];
                                  await receiveStream.ReadAsync(buffer, 0, buffer.Length);
                                  liveClient.Send(buffer);
                              }
                          }
                      }
                  }
                  catch (Exception e)
                  {
                      Console.WriteLine(e.Message);
                  }

                  // Stop the connection
                  await liveClient.Stop();

                  // Teardown Library
                  Library.Terminate();
              }
              catch (Exception e)
              {
                  Console.WriteLine(e.Message);
              }
          }
      }
  }
  ```

  ```go Go
  // Example filename: main.go
  package main

  import (
  	"bufio"
  	"context"
  	"fmt"
  	"net/http"
  	"os"
  	"reflect"

  	interfaces "github.com/deepgram/deepgram-go-sdk/pkg/client/interfaces"
  	client "github.com/deepgram/deepgram-go-sdk/pkg/client/live"
  )

  const (
  	STREAM_URL = "http://stream.live.vc.bbcmedia.co.uk/bbc_world_service"
  )

  func main() {
  	// STEP 1: init Deepgram client library
  	client.InitWithDefault()

  	// STEP 2: define context to manage the lifecycle of the request
  	ctx := context.Background()

  	// STEP 3: define options for the request
  	transcriptOptions := interfaces.LiveTranscriptionOptions{
  		Model:       "nova-3",
  		Language:    "en-US",
  		SmartFormat: true,
  	}

  	// STEP 4: create a Deepgram client using default settings
  	// NOTE: you can set your API KEY in your bash profile by typing the following line in your shell:
  	// export DEEPGRAM_API_KEY = "YOUR_DEEPGRAM_API_KEY"
  	dgClient, err := client.NewForDemo(ctx, &transcriptOptions)
  	if err != nil {
  		fmt.Println("ERROR creating LiveTranscription connection:", err)
  		return
  	}

  	// STEP 5: connect to the Deepgram service
  	bConnected := dgClient.Connect()
  	if !bConnected {
  		fmt.Println("Client.Connect failed")
  		os.Exit(1)
  	}

  	// STEP 6: create an HTTP client to stream audio data
  	httpClient := new(http.Client)

  	// STEP 7: create an HTTP stream
  	res, err := httpClient.Get(STREAM_URL)
  	if err != nil {
  		fmt.Printf("httpClient.Get failed. Err: %v\n", err)
  		return
  	}

  	fmt.Printf("Stream is up and running %s\n", reflect.TypeOf(res))

  	go func() {
  		// STEP 8: feed the HTTP stream to the Deepgram client (this is a blocking call)
  		dgClient.Stream(bufio.NewReader(res.Body))
  	}()

  	// STEP 9: wait for user to exit
  	fmt.Print("Press ENTER to exit!\n\n")
  	input := bufio.NewScanner(os.Stdin)
  	input.Scan()

  	// STEP 10: close HTTP stream
  	res.Body.Close()

  	// STEP 11: close the Deepgram client
  	dgClient.Stop()

  	fmt.Printf("Program exiting...\n")
  }
  ```

  ```java Java
  // Example filename: Main.java
  // https://github.com/deepgram/deepgram-java-sdk

  import java.util.concurrent.CompletableFuture;
  import java.util.concurrent.CountDownLatch;
  import java.util.concurrent.TimeUnit;
  import com.deepgram.DeepgramClient;
  import com.deepgram.resources.listen.v1.types.ListenV1CloseStream;
  import com.deepgram.resources.listen.v1.types.ListenV1CloseStreamType;
  import com.deepgram.resources.listen.v1.websocket.V1ConnectOptions;
  import com.deepgram.resources.listen.v1.websocket.V1WebSocketClient;
  import com.deepgram.types.ListenV1Model;

  public class Main {
      public static void main(String[] args) throws Exception {
          // Create a client using DEEPGRAM_API_KEY from the environment
          DeepgramClient client = DeepgramClient.builder().build();

          V1WebSocketClient wsClient = client.listen().v1().v1WebSocket();
          CountDownLatch closeLatch = new CountDownLatch(1);

          wsClient.onResults(result -> {
              if (result.getChannel() != null
                      && result.getChannel().getAlternatives() != null
                      && !result.getChannel().getAlternatives().isEmpty()) {
                  String transcript = result.getChannel().getAlternatives().get(0).getTranscript();
                  boolean isFinal = result.getIsFinal().orElse(false);
                  if (transcript != null && !transcript.isEmpty()) {
                      System.out.printf("%s %s%n", isFinal ? "[final]  " : "[interim]", transcript);
                  }
              }
          });

          wsClient.onDisconnected(reason -> closeLatch.countDown());

          // Connect with model selection
          CompletableFuture<Void> connectFuture = wsClient.connect(
              V1ConnectOptions.builder()
                  .model(ListenV1Model.NOVA3)
                  .smartFormat(true)
                  .build()
          );
          connectFuture.get(10, TimeUnit.SECONDS);

          // In a real application, stream audio chunks here:
          // wsClient.sendMedia(audioChunk);

          wsClient.sendCloseStream(
              ListenV1CloseStream.builder()
                  .type(ListenV1CloseStreamType.CLOSE_STREAM)
                  .build()
          );

          closeLatch.await(15, TimeUnit.SECONDS);
          wsClient.disconnect();
      }
  }
  ```
</CodeGroup>

<Info>
  The above example includes the parameter `model=nova-3`, which tells the API to use Deepgram's latest model. Removing this parameter will result in the API using the default model, which is currently `model=base`.

  It also includes Deepgram's [Smart Formatting](/docs/smart-format) feature, `smart_format=true`. This will format currency amounts, phone numbers, email addresses, and more for enhanced transcript readability.
</Info>

## Non-SDK Code Examples

If you would like to try out making a Deepgram speech-to-text request in a specific language (but not using Deepgram's SDKs), we offer a library of code-samples in this [Github repo](https://github.com/deepgram-devs/code-samples). However, we recommend first trying out our SDKs.

## Results

In order to see the results from Deepgram, you must run the application. Run your application from the terminal. Your transcripts will appear in your shell.

<CodeGroup>
  ```javascript JavaScript
  # Run your application using the file you created in the previous step
  # Example: node index.js

  node YOUR_FILE_NAME.js
  ```

  ```shell Python
  # Run your application using the file you created in the previous step
  # Example: python main.py

  python YOUR_FILE_NAME.py
  ```

  ```shell C#
  # Run your application using the file you created in the previous step
  # Example: dotnet run Program.cs

  dotnet run YOUR_FILE_NAME.cs
  ```

  ```shell Go
  # Run your application using the file you created in the previous step
  # Example: go run main.go

  go run YOUR_FILE_NAME.go
  ```

  ```shell Java
  mvn compile exec:java -Dexec.mainClass="Main"
  ```
</CodeGroup>

<Warning>
  Deepgram does not store transcripts, so the Deepgram API response is the only opportunity to retrieve the transcript. Make sure to save output or [return transcriptions to a callback URL for custom processing](/docs/callback/).
</Warning>

### Analyze the Response

The responses that are returned will look similar to this:

<CodeGroup>
  ```json JSON
  {
    "type": "Results",
    "channel_index": [
      0,
      1
    ],
    "duration": 1.98,
    "start": 5.99,
    "is_final": true,
    "speech_final": true,
    "channel": {
      "alternatives": [
        {
          "transcript": "Tell me more about this.",
          "confidence": 0.99964225,
          "words": [
            {
              "word": "tell",
              "start": 6.0699997,
              "end": 6.3499994,
              "confidence": 0.99782443,
              "punctuated_word": "Tell"
            },
            {
              "word": "me",
              "start": 6.3499994,
              "end": 6.6299996,
              "confidence": 0.9998324,
              "punctuated_word": "me"
            },
            {
              "word": "more",
              "start": 6.6299996,
              "end": 6.79,
              "confidence": 0.9995466,
              "punctuated_word": "more"
            },
            {
              "word": "about",
              "start": 6.79,
              "end": 7.0299997,
              "confidence": 0.99984455,
              "punctuated_word": "about"
            },
            {
              "word": "this",
              "start": 7.0299997,
              "end": 7.2699995,
              "confidence": 0.99964225,
              "punctuated_word": "this"
            }
          ]
        }
      ]
    },
    "metadata": {
      "request_id": "52cc0efe-fa77-4aa7-b79c-0dda09de2f14",
      "model_info": {
        "name": "2-general-nova",
        "version": "2024-01-18.26916",
        "arch": "nova-2"
      },
      "model_uuid": "c0d1a568-ce81-4fea-97e7-bd45cb1fdf3c"
    },
    "from_finalize": false
  }
  ```
</CodeGroup>

In this default response, we see:

* `transcript`: the transcript for the audio segment being processed.
* `confidence`: a floating point value between 0 and 1 that indicates overall transcript reliability. Larger values indicate higher confidence.
* `words`: an object containing each `word` in the transcript, along with its `start` time and `end` time (in seconds) from the beginning of the audio stream, and a `confidence` value.
  * Because we passed the `smart_format: true` option to the `transcription.prerecorded` method, each word object also includes its `punctuated_word` value, which contains the transformed word after punctuation and capitalization are applied.
* `speech_final`: tells us this segment of speech naturally ended at this point. By default, Deepgram live streaming looks for any deviation in the natural flow of speech and returns a finalized response at these places. To learn more about this feature, see [Endpointing](/docs/endpointing/).
* `is_final`: If this says `false`, it is indicating that Deepgram will continue waiting to see if more data will improve its predictions. Deepgram live streaming can return a series of interim transcripts followed by a final transcript. To learn more, see [Interim Results](/docs/interim-results/).

<Info>
  Endpointing can be used with Deepgram's [Interim Results](/docs/interim-results/) feature. To compare and contrast these features, and to explore best practices for using them together, see [Using Endpointing and Interim Results with Live Streaming Audio](/docs/understand-endpointing-interim-results/).
</Info>

If your scenario requires you to keep the connection alive even while data is not being sent to Deepgram, you can send periodic KeepAlive messages to essentially "pause" the connection without closing it. To learn more, see [KeepAlive](/docs/audio-keep-alive).

## What's Next?

Now that you've gotten transcripts for streaming audio, enhance your knowledge by exploring the following areas. You can also check out our [Live Streaming API Reference](/reference/speech-to-text/listen-streaming) for a list of all possible parameters.

### Read the Feature Guides

Deepgram's features help you to customize your transcripts.

* [Language](/docs/language): Learn how to transcribe audio in other languages.
* [Feature Overview](/docs/stt-streaming-feature-overview): Review the list of features available for streaming speech-to-text. Then, dive into individual guides for more details.

### Tips and tricks

* [End of speech detection](/docs/understanding-end-of-speech-detection) - Learn how to pinpoint end of speech post-speaking more effectively.
* [Using interim results](/docs/using-interim-results) - Learn how to use preliminary results provided during the streaming process which can help with speech detection.
* [Measuring streaming latency](/docs/measuring-streaming-latency) - Learn how to measure latency in real-time streaming of audio.

### Add Your Audio

* Ready to connect Deepgram to your own audio source? Start by reviewing [how to determine your audio format](/docs/determining-your-audio-format-for-live-streaming-audio/) and format your API request accordingly.
* Then, check out our [Live Streaming Starter Kit](/docs/getting-started-with-the-streaming-test-suite). It's the perfect "102" introduction to integrating your own audio.

### Explore Use Cases

* Learn about the different ways you can use Deepgram products to help you meet your business objectives. [Explore Deepgram's use cases](/docs/transcribe-recorded-calls-with-twilio).

### Transcribe Pre-recorded Audio

* Now that you know how to transcribe streaming audio, check out how you can use Deepgram to transcribe pre-recorded audio. To learn more, see [Getting Started with Pre-recorded Audio](/docs/pre-recorded-audio).

***
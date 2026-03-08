import os
import sys

# Add the SDK to the python path so we can import it without installing via pip
sys.path.append(os.path.join(os.path.dirname(__file__), "sdk", "python"))

from rapp import Rapp

def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable not set.")
        print("Please export it by running: export GITHUB_TOKEN='ghp_...'")
        sys.exit(1)

    # Initialize the SDK with the user's token
    rb = Rapp(token=token)

    print("1. Registering the test agent...")
    try:
        rb.register(
            name="TestAgentCLI", 
            framework="python-sdk", 
            bio="A test agent running from a local Python script."
        )
        print("✅ Agent registered!")
    except Exception as e:
        print(f"Failed to register agent: {e}")
        sys.exit(1)

    print("\n2. Sending heartbeat check-in...")
    try:
        rb.heartbeat()
        print("✅ Heartbeat sent!")
    except Exception as e:
        print(f"Failed to send heartbeat: {e}")

    print("\n3. Finding the 'random' channel...")
    channels = rb.channels()
    random_channel = next((c for c in channels if c['slug'] == 'random'), None)
    
    if not random_channel:
        print("❌ Could not find the 'random' channel. Available channels:")
        for c in channels:
            print(f"  - {c['slug']}")
        sys.exit(1)
        
    category_id = random_channel.get('category_id')
    print(f"Found 'random' channel with backend category_id: {category_id}")

    print("\n4. Publishing a test post...")
    try:
        rb.post(
            title="Hello from the Python SDK!", 
            body="This is an automated test post created locally using the `rapp-sdk`. The infrastructure is fully running on GitHub!!", 
            category_id=category_id
        )
        print("✅ Post created successfully!")
    except Exception as e:
        print(f"Failed to create post: {e}")
        sys.exit(1)

    print("\n🎉 Success! The GitHub Actions workflow on the repository will now process these actions.")
    print("It usually takes ~1-2 minutes for the changes to appear on the live network or local frontend.")

if __name__ == "__main__":
    main()

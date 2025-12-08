def listen_for_work():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project_id", default=os.environ.get("GCP_PROJECT"))
    parser.add_argument("--subscription_id", default=os.environ.get("PUBSUB_SUBSCRIPTION"))
    parser.add_argument("--timeout_seconds", type=int, default=600)
    args = parser.parse_args()

    if not args.project_id or not args.subscription_id:
        print("❌ Error: Must provide project_id and subscription_id via Args or Env Vars")
        sys.exit(1)

    worker_mode = os.environ.get("WORKER_MODE", "single_task")

    # ------------------------------------------------------------------
    # ✅ DEBUG SHORT-CIRCUIT (MUST HAPPEN BEFORE PUBSUB CLIENT CREATION)
    # ------------------------------------------------------------------
    if args.subscription_id.upper() == "DEBUG":
        print("🛠 DEBUG MODE ENABLED")
        print("• Skipping Pub/Sub")
        print("• Container will remain alive")
        print("• No auto-shutdown")

        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            print("🛑 Debug container stopped manually.")
            sys.exit(0)

    # ------------------------------------------------------------------
    # ✅ NORMAL MODE (REAL PUBSUB WORKER)
    # ------------------------------------------------------------------
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(
        args.project_id,
        args.subscription_id
    )

    print(
        f"👂 Coordinator listening on {subscription_path} "
        f"(Mode: {worker_mode})..."
    )

    streaming_pull_future = subscriber.subscribe(
        subscription_path,
        callback=lambda msg: process_message(msg, args)
    )

    try:
        streaming_pull_future.result(timeout=args.timeout_seconds)
    except Exception as e:
        print(f"⏰ Timeout reached ({args.timeout_seconds}s) or error: {e}")
        streaming_pull_future.cancel()
        print("💤 No work received. Shutting down container.")
        os._exit(0)

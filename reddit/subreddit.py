import re
import praw
from praw.models import MoreComments
from prawcore.exceptions import ResponseException

from utils import settings
from utils.ai_methods import sort_by_similarity
from utils.console import print_step, print_substep
from utils.posttextparser import posttextparser
from utils.subreddit import get_subreddit_undone
from utils.videos import check_done
from utils.voice import sanitize_text


def get_subreddit_threads(POST_ID: str):
    """Returns a list of threads from the AskReddit subreddit."""

    print_substep("Logging into Reddit.")

    content = {}
    if settings.config["reddit"]["creds"]["2fa"]:
        print("\nEnter your two-factor authentication code from your authenticator app.\n")
        code = input("> ")
        print()
        pw = settings.config["reddit"]["creds"]["password"]
        passkey = f"{pw}:{code}"
    else:
        passkey = settings.config["reddit"]["creds"]["password"]
    username = settings.config["reddit"]["creds"]["username"]
    if str(username).casefold().startswith("u/"):
        username = username[2:]
    try:
        reddit = praw.Reddit(
            client_id=settings.config["reddit"]["creds"]["client_id"],
            client_secret=settings.config["reddit"]["creds"]["client_secret"],
            user_agent="Accessing Reddit threads",
            username=username,
            password=passkey,
            check_for_async=False,
        )
    except ResponseException as e:
        if e.response.status_code == 401:
            print("Invalid credentials - please check them in config.toml")
    except:
        print("Something went wrong...")

    min_upvotes = settings.config["reddit"]["thread"]["min_upvotes"]
    sort_type = settings.config["reddit"]["thread"]["sort_type"]
    subreddit_choice = settings.config["reddit"]["thread"]["subreddit"].lstrip('r/')

    print_step("Getting subreddit threads...")

    similarity_score = 0
    if not settings.config["reddit"]["thread"][
        "subreddit"
    ]:  # note to user. you can have multiple subreddits via reddit.subreddit("redditdev+learnpython")
        try:
            subreddit = reddit.subreddit(
                re.sub(r"r\/", "", input("What subreddit would you like to pull from? "))
                # removes the r/ from the input
            )
        except ValueError:
            subreddit = reddit.subreddit("askreddit")
            print_substep("Subreddit not defined. Using AskReddit.")
    else:
        sub = settings.config["reddit"]["thread"]["subreddit"]
        print_substep(f"Using subreddit: r/{sub} from TOML config")
        subreddit_choice = sub
        if str(subreddit_choice).casefold().startswith("r/"):  # removes the r/ from the input
            subreddit_choice = subreddit_choice[2:]
        subreddit = reddit.subreddit(subreddit_choice)

    if POST_ID:  # would only be called if there are multiple queued posts
        submission = reddit.submission(id=POST_ID)

    elif (
        settings.config["reddit"]["thread"]["post_id"]
        and len(str(settings.config["reddit"]["thread"]["post_id"]).split("+")) == 1
    ):
        submission = reddit.submission(id=settings.config["reddit"]["thread"]["post_id"])
    elif settings.config["ai"]["ai_similarity_enabled"]:  # ai sorting based on comparison
        threads = subreddit.hot(limit=50)
        keywords = settings.config["ai"]["ai_similarity_keywords"].split(",")
        keywords = [keyword.strip() for keyword in keywords]
        # Reformat the keywords for printing
        keywords_print = ", ".join(keywords)
        print(f"Sorting threads by similarity to the given keywords: {keywords_print}")
        threads, similarity_scores = sort_by_similarity(threads, keywords)
        submission, similarity_score = get_subreddit_undone(
            threads, subreddit, similarity_scores=similarity_scores
        )
    else:
        threads = list(getattr(subreddit, str(sort_type))(limit=25))
        submission = get_subreddit_undone(threads, subreddit)

    # Check submission
    if submission is None:
        return get_subreddit_threads(POST_ID)  # submission already done. rerun

    elif not submission.num_comments and settings.config["settings"]["storymode"] == "false":
        print_substep("No comments found. Skipping.")
        exit()

    submission = check_done(submission)  # double-checking

    upvotes = submission.score
    ratio = submission.upvote_ratio * 100
    num_comments = submission.num_comments
    threadurl = f"https://reddit.com{submission.permalink}"

    print_substep(f"Video will be: {submission.title} :thumbsup:", style="bold green")
    print_substep(f"Thread url is: {threadurl} :thumbsup:", style="bold green")
    print_substep(f"Thread has {upvotes} upvotes", style="bold blue")
    print_substep(f"Thread has a upvote ratio of {ratio}%", style="bold blue")
    print_substep(f"Thread has {num_comments} comments", style="bold blue")
    if similarity_score:
        print_substep(
            f"Thread has a similarity score up to {round(similarity_score * 100)}%",
            style="bold blue",
        )
    if submission.score < min_upvotes:
        print_substep(
            f"Thread has {submission.score} upvotes which is below the minimum threshold of {min_upvotes}. Skipping.")
        return get_subreddit_threads(POST_ID)

    content["thread_url"] = threadurl
    content["thread_title"] = submission.title
    content["thread_id"] = submission.id
    content["is_nsfw"] = submission.over_18
    content["comments"] = []
    content["thread_post"] = ""  # Default value
    if settings.config["settings"]["storymode"]:
        if settings.config["settings"]["storymodemethod"] == 1:
            content["thread_post"] = posttextparser(submission.selftext)
        else:
            content["thread_post"] = submission.selftext
    else:
        # Process comments
        min_comment_length = int(str(settings.config["reddit"]["thread"]["min_comment_length"]))
        max_comment_length = int(str(settings.config["reddit"]["thread"]["max_comment_length"]))
        min_comment_upvotes = int(str(settings.config["reddit"]["thread"]["min_comment_upvotes"]))

        for comment in submission.comments:
            if isinstance(comment, MoreComments) or comment.body in ["[removed]", "[deleted]"] or comment.stickied:
                continue

            sanitised = sanitize_text(comment.body)
            if not sanitised or sanitised == " ":
                continue

            if min_comment_length <= len(comment.body) <= max_comment_length and comment.score >= min_comment_upvotes:
                if comment.author and sanitised:
                    content["comments"].append({
                        "comment_body": comment.body,
                        "comment_url": comment.permalink,
                        "comment_id": comment.id,
                    })

    print_substep("Received subreddit threads Successfully.", style="bold green")
    return content

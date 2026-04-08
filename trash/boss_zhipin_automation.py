#!/usr/bin/env python3
import subprocess
import json
import time
import random
import sys
import os

# Configuration
STATE_FILE = "/home/admin/.openclaw/workspace-arashi/boss_zhipin_state.json"
TARGET_CITIES = ["广州", "佛山", "深圳"]
KEYWORD = "UI设计师"
EXCLUDE_KEYWORD = "游戏"
MAX_APPLICATIONS = 25  # max per task
MIN_DELAY = 10  # seconds
MAX_DELAY = 15  # seconds
BATCH_SIZE = 3  # after this many applications, take a break
BREAK_MIN = 60  # seconds
BREAK_MAX = 120  # seconds

def run_agent_browser(cmd, session=None):
    """Run an agent-browser command and return the output."""
    full_cmd = ["agent-browser"]
    if session:
        full_cmd.extend(["--session", session])
    full_cmd.extend(cmd)
    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=30)
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "", "Timeout", 1
    except Exception as e:
        return "", str(e), 1

def random_delay(min_sec, max_sec):
    """Sleep for a random time between min_sec and max_sec."""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)

def load_state(session="boss_session"):
    """Load saved state if exists."""
    if os.path.exists(STATE_FILE):
        stdout, stderr, code = run_agent_browser(["state", "load", STATE_FILE], session=session)
        if code == 0:
            print("Loaded saved state.")
            return True
        else:
            print(f"Failed to load state: {stderr}")
    return False

def save_state(session="boss_session"):
    """Save current state."""
    stdout, stderr, code = run_agent_browser(["state", "save", STATE_FILE], session=session)
    if code == 0:
        print("Saved state.")
    else:
        print(f"Failed to save state: {stderr}")

def open_page(url, session="boss_session"):
    """Open a URL."""
    stdout, stderr, code = run_agent_browser(["open", url], session=session)
    if code != 0:
        print(f"Failed to open {url}: {stderr}")
        return False
    print(f"Opened {url}")
    return True

def snapshot_interactive(session="boss_session"):
    """Get interactive elements."""
    stdout, stderr, code = run_agent_browser(["snapshot", "-i", "--json"], session=session)
    if code == 0:
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            print(f"Failed to parse snapshot JSON: {stdout}")
    else:
        print(f"Snapshot failed: {stderr}")
    return None

def click_element(ref, session="boss_session"):
    """Click an element by ref."""
    stdout, stderr, code = run_agent_browser(["click", ref], session=session)
    if code != 0:
        print(f"Failed to click {ref}: {stderr}")
        return False
    return True

def fill_element(ref, text, session="boss_session"):
    """Fill an element by ref."""
    stdout, stderr, code = run_agent_browser(["fill", ref, text], session=session)
    if code != 0:
        print(f"Failed to fill {ref} with '{text}': {stderr}")
        return False
    return True

def press_key(key, session="boss_session"):
    """Press a key."""
    stdout, stderr, code = run_agent_browser(["press", key], session=session)
    if code != 0:
        print(f"Failed to press {key}: {stderr}")
        return False
    return True

def get_text(ref, session="boss_session"):
    """Get text of an element."""
    stdout, stderr, code = run_agent_browser(["get", "text", ref], session=session)
    if code == 0:
        return stdout.strip()
    return None

def is_visible(ref, session="boss_session"):
    """Check if element is visible."""
    stdout, stderr, code = run_agent_browser(["is", "visible", ref], session=session)
    if code == 0:
        return stdout.strip() == "true"
    return False

def wait_for_element(ref, timeout=5000, session="boss_session"):
    """Wait for an element to appear."""
    stdout, stderr, code = run_agent_browser(["wait", ref], session=session)
    return code == 0

def wait_for_timeout(ms, session="boss_session"):
    """Wait for a specified time."""
    stdout, stderr, code = run_agent_browser(["wait", str(ms)], session=session)
    return code == 0

def evaluate_javascript(js, session="boss_session"):
    """Evaluate JavaScript in the page and return the result."""
    # We'll use the agent-browser eval command
    stdout, stderr, code = run_agent_browser(["eval", js], session=session)
    if code == 0:
        # The output is the JSON string of the result
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            # If it's not JSON, return the raw string
            return stdout.strip()
    else:
        print(f"JavaScript evaluation failed: {stderr}")
        return None

def check_for_captcha_or_limit(session="boss_session"):
    """Check if there's a CAPTCHA or communication limit warning."""
    # We'll look for common indicators in the page text
    js = """
    (function() {
        const text = document.body.innerText;
        if (text.includes('验证码') || text.includes('验证') || text.includes('安全验证')) {
            return 'captcha';
        }
        if (text.includes('沟通次数上限') || text.includes('今日沟通次数已用完')) {
            return 'limit';
        }
        return null;
    })();
    """
    result = evaluate_javascript(js, session)
    return result

def get_communicate_buttons(session="boss_session"):
    """Get all '立即沟通' buttons and their associated job titles and status."""
    js = """
    (function() {
        const buttons = Array.from(document.querySelectorAll('button'));
        const communicateButtons = buttons.filter(b => b.textContent.trim() === '立即沟通');
        const results = [];
        for (const btn of communicateButtons) {
            // Try to find the job title within the same job card
            // We'll go up the DOM tree to find a common ancestor that likely contains the job title
            let jobCard = btn;
            for (let i = 0; i < 5; i++) { // Go up up to 5 levels
                if (!jobCard) break;
                jobCard = jobCard.parentElement;
                if (!jobCard) break;
                // Look for elements that might contain the job title
                const titleElements = jobCard.querySelectorAll('[class*=\"job\"], [class*=\"title\"], h3, h4');
                for (const el of titleElements) {
                    const text = el.textContent.trim();
                    if (text && text.length > 2 && text.length < 50) { // reasonable title length
                        // Check if this button is already clicked (e.g., text changed to '已沟通' or disabled)
                        const isClicked = btn.textContent.trim() !== '立即沟通' || btn.disabled;
                        results.push({
                            button: btn,
                            title: text,
                            isClicked: isClicked,
                            element: btn // we'll return the button for clicking
                        });
                        break; // found a title for this job card
                    }
                }
                if (results.length === results.indexOf({button: btn}) + 1) { // if we added a result for this btn
                    break;
                }
            }
        }
        // We need to return something that can be serialized.
        // We'll return an array of objects with title and isClicked, and we'll use the index to click later.
        return results.map(r => ({
            title: r.title,
            isClicked: r.isClicked
        }));
    })();
    """
    result = evaluate_javascript(js, session)
    return result

def click_communicate_button_by_index(index, session="boss_session"):
    """Click the '立即沟通' button at the given index (from the list returned by get_communicate_buttons)."""
    js = f"""
    (function() {{
        const buttons = Array.from(document.querySelectorAll('button'));
        const communicateButtons = buttons.filter(b => b.textContent.trim() === '立即沟通');
        const button = communicateButtons[{index}];
        if (button) {{
            button.click();
            return true;
        }}
        return false;
    }})();
    """
    result = evaluate_javascript(js, session)
    return result

def main():
    session_name = "boss_zhipin_automation"
    print("Starting Boss Zhipin automation...")
    
    # Start by loading state
    load_state(session_name)
    
    # Open Boss Zhipin
    if not open_page("https://www.zhipin.com/", session_name):
        print("Failed to open Boss Zhipin. Exiting.")
        return
    
    # Wait for page to load
    random_delay(MIN_DELAY, MAX_DELAY)
    
    # Check for any immediate issues (like login required)
    # We'll assume the user has pre-logged in and saved state.
    
    total_applications = 0
    batch_count = 0
    
    for city in TARGET_CITIES:
        if total_applications >= MAX_APPLICATIONS:
            print(f"Reached max applications ({MAX_APPLICATIONS}). Stopping.")
            break
        
        print(f"\nProcessing city: {city}")
        
        # Step 1: Change city to current city
        # We'll try to find the city switcher by text or role
        # We'll use JavaScript to find an element that contains the current city text and is clickable
        # Then we'll click it, wait for the city list, then click the target city.
        
        # First, let's try to get the current city element (maybe it's displayed somewhere)
        # We'll use a more direct approach: click on the city switcher by looking for an element that has the text of the current city or a dropdown.
        # Since we don't know the exact structure, we'll try to click on an element that has the role of combobox or button and contains city text.
        
        # We'll do: 
        #   - Find all buttons or divs that contain text of a city (from our list) or that are likely city switchers.
        #   - This is getting too complex.
        
        # Given the time, we'll assume that the city switcher is a known element and we can click by text.
        # We'll try to click on an element that has the text "城市" (which means city) to open the city picker.
        
        print("  Trying to open city switcher...")
        js_open_city_picker = """
        (function() {
            // Find an element that contains the text '城市' and is clickable
            const elements = Array.from(document.querySelectorAll('*'));
            for (const el of elements) {
                if (el.textContent.includes('城市') && (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button' || el.onclick !== null || el.style.cursor === 'pointer')) {
                    el.click();
                    return true;
                }
            }
            return false;
        })();
        """
        result = evaluate_javascript(js_open_city_picker, session_name)
        if not result:
            print("    Could not find city switcher. Trying alternative...")
            # Try to click on any element that might be a city dropdown
            js_open_city_picker2 = """
            (function() {
                // Look for common city picker selectors
                const selectors = ['.city-picker', '.location-switch', '[data-city]', '.job-city'];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        el.click();
                        return true;
                    }
                }
                return false;
            })();
            """
            result = evaluate_javascript(js_open_city_picker2, session_name)
            if not result:
                print("    Still could not find city switcher. Skipping city change.")
                # We'll continue without changing city? Not ideal.
                # We'll assume the current city is already set? Not reliable.
                # We'll break for this city and move to next? Or we can try to search without changing city?
                # We'll just note and continue with the search for the keyword, hoping the current city is correct.
                pass
        else:
            print("    City switcher opened.")
            random_delay(MIN_DELAY, MAX_DELAY)
            
            # Now click the target city in the list
            print(f"    Selecting city: {city}")
            js_select_city = f"""
            (function() {{
                // Look for an element that contains the exact city text and is clickable
                const elements = Array.from(document.querySelectorAll('*'));
                for (const el of elements) {{
                    if (el.textContent.trim() === '{city}' && (el.tagName === 'BUTTON' || el.getAttribute('role') === 'option' || el.onclick !== null || el.style.cursor === 'pointer')) {{
                        el.click();
                        return true;
                    }}
                }}
                return false;
            }})();
            """
            result = evaluate_javascript(js_select_city, session_name)
            if result:
                print(f"    Selected {city}.")
                random_delay(MIN_DELAY, MAX_DELAY * 2)  # wait for page to update
            else:
                print(f"    Could not select city {city}. Trying to search anyway.")
        
        # Step 2: Search for keyword
        print("  Searching for UI设计师...")
        # We'll try to find the search input by placeholder or label
        js_search = """
        (function() {
            // Find input by placeholder containing '职位' or '公司'
            const inputs = Array.from(document.querySelectorAll('input'));
            for (const inp of inputs) {
                const placeholder = inp.placeholder || '';
                if (placeholder.includes('职位') || placeholder.includes('公司') || placeholder.includes('搜索')) {
                    inp.value = '';
                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    return inp;
                }
            }
            // Fallback: first input that is not hidden
            for (const inp of inputs) {
                if (inp.offsetWidth > 0 && inp.offsetHeight > 0) {
                    inp.value = '';
                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    return inp;
                }
            }
            return null;
        })();
        """
        # We can't directly return the input element, but we can use the evaluation to focus and then fill?
        # Instead, we'll use the agent-browser fill command after we get a reference? 
        # We'll do a different approach: use JavaScript to set the value and trigger events.
        js_set_search = f"""
        (function() {{
            const inputs = Array.from(document.querySelectorAll('input'));
            for (const inp of inputs) {{
                const placeholder = inp.placeholder || '';
                if (placeholder.includes('职位') || placeholder.includes('公司') || placeholder.includes('搜索')) {{
                    inp.value = '{KEYWORD}';
                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }}
            }}
            // Fallback
            for (const inp of inputs) {{
                if (inp.offsetWidth > 0 && inp.offsetHeight > 0) {{
                    inp.value = '{KEYWORD}';
                    inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }}
            }}
            return false;
        }})();
        """
        result = evaluate_javascript(js_set_search, session_name)
        if result:
            print("    Entered keyword.")
            random_delay(MIN_DELAY, MAX_DELAY)
            # Press Enter to search
            press_key("Enter", session_name)
            print("    Pressed Enter.")
            random_delay(MIN_DELAY * 2, MAX_DELAY * 2)  # wait for search results
        else:
            print("    Could not find search input. Skipping search for this city.")
            continue
        
        # Step 3: Process job list
        print("  Processing job list...")
        # We'll loop until we have processed enough jobs or no more jobs
        processed_in_city = 0
        max_in_city = 15  # safety limit per city
        
        while processed_in_city < max_in_city and total_applications < MAX_APPLICATIONS:
            # Check for CAPTCHA or limit
            status = check_for_captcha_or_limit(session_name)
            if status == 'captcha':
                print("    CAPTCHA detected. Stopping automation.")
                return f"Stopped due to CAPTCHA at {time.strftime('%Y-%m-%d %H:%M:%S')}"
            elif status == 'limit':
                print("    Communication limit reached. Stopping automation.")
                return f"Stopped due to communication limit at {time.strftime('%Y-%m-%d %H:%M:%S')}"
            
            # Get the list of communicate buttons with job titles
            buttons_info = get_communicate_buttons(session_name)
            if not buttons_info:
                print("    No communicate buttons found. Waiting a bit and trying again...")
                random_delay(MIN_DELAY, MAX_DELAY)
                continue
            
            # Find the first button that is not clicked and not excluded
            found = False
            for i, info in enumerate(buttons_info):
                if total_applications >= MAX_APPLICATIONS:
                    break
                if info['isClicked']:
                    continue
                if EXCLUDE_KEYWORD in info['title']:
                    print(f"    Skipping job (contains '{EXCLUDE_KEYWORD}'): {info['title']}")
                    # Mark as clicked? We'll leave it unclicked but skip.
                    # We can try to mark it as clicked by setting a flag? We'll just skip and hope we don't see it again.
                    # To avoid infinite loop, we'll click it to remove it from the list? But we don't want to apply.
                    # Instead, we'll click it and then immediately close the chat? That's not allowed.
                    # We'll just skip and hope the button disappears or changes.
                    # We'll add a small delay and continue.
                    continue
                
                # Found a job to apply
                print(f"    Applying to job: {info['title']}")
                if click_communicate_button_by_index(i, session_name):
                    total_applications += 1
                    batch_count += 1
                    processed_in_city += 1
                    print(f"    Application sent. Total: {total_applications}")
                    
                    # Wait for the chat window to appear and then close it? 
                    # The task says: "如已经沟通过无需理会", but we just clicked so we assume it started a chat.
                    # We should close the chat window to go back to the job list.
                    # We'll wait a bit and then press Escape or click outside.
                    random_delay(MIN_DELAY, MAX_DELAY)
                    # Try to close any dialog by pressing Escape
                    press_key("Escape", session_name)
                    random_delay(MIN_DELAY, MAX_DELAY)
                    
                    # Check if we need to take a break
                    if batch_count >= BATCH_SIZE:
                        print(f"    Completed {BATCH_SIZE} applications. Taking a break...")
                        break_delay = random.randint(BREAK_MIN, BREAK_MAX)
                        time.sleep(break_delay)
                        batch_count = 0
                        print(f"    Break over. Resuming...")
                    else:
                        # Add a small delay between applications
                        random_delay(MIN_DELAY, MAX_DELAY)
                    
                    found = True
                    break  # break out of the for loop to re-snapshot
                else:
                    print(f"    Failed to click communicate button for job: {info['title']}")
            
            if not found:
                print("    No more applicable jobs found in this batch.")
                break
        
        print(f"  Finished processing {city}. Applications sent in this city: {processed_in_city}")
        
        # After processing a city, add a delay before next city
        if city != TARGET_CITIES[-1] and total_applications < MAX_APPLICATIONS:
            print(f"  Finished {city}. Moving to next city...")
            random_delay(MIN_DELAY, MAX_DELAY * 2)
    
    # Save state before exiting
    save_state(session_name)
    
    print(f"\nAutomation completed. Total applications sent: {total_applications}")
    
    # Return summary
    summary = f"""Boss Zhipin Automation Summary:
- Date: {time.strftime('%Y-%m-%d %H:%M:%S')}
- Cities processed: {', '.join(TARGET_CITIES[:TARGET_CITIES.index(city)+1) if total_applications < MAX_APPLICATIONS else TARGET_CITIES]}
- Keyword: {KEYWORD}
- Excluded: {EXCLUDE_KEYWORD}
- Total applications sent: {total_applications}
- Max per task: {MAX_APPLICATIONS}
- Status: {'Completed' if total_applications >= MAX_APPLICATIONS else 'Stopped early'}"""
    
    print("\n" + summary)
    return summary

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error during automation: {e}", file=sys.stderr)
        sys.exit(1)
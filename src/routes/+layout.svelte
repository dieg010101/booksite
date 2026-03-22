<script lang="ts">
	// This imports the content of whatever page the user is currently on
	let { children } = $props();
  </script>
  
  <div class="app-container">
	<header class="top-nav">
	  <div class="logo">
		<a href="/">Book Platform</a>
	  </div>
  
	  <nav class="nav-links">
		<a href="/feed">FEED</a>
		<a href="/explore">EXPLORE</a>
		<a href="/lists">LISTS</a>
		<a href="/stats">STATS</a>
		<a href="/search">SEARCH</a>
	  </nav>
  
	  <div class="system-time">
		<span>01/03/2025</span>
		<span>12:18AM</span>
	  </div>
	</header>
  
	<main class="page-content">
	  {@render children()}
	</main>
  
	<footer class="site-footer">
	  <nav class="footer-links">
		<a href="/settings">Settings</a>
		<a href="/privacy">Privacy Policy</a>
		<a href="/cookies">Cookies</a>
	  </nav>
	  <div class="copyright">2025. Lorem Ipsum Art Group. All Rights Reserved</div>
	</footer>
  </div>
  
  <style>
	/* Global reset for the dark theme */
	:global(body) {
	  margin: 0;
	  background-color: #000000;
	  color: #FFFFFF;
	  font-family: 'Roboto', sans-serif;
	}
  
	.app-container {
	  display: flex;
	  flex-direction: column;
	  min-height: 100vh;
	}
  
	.top-nav {
	  display: flex;
	  justify-content: space-between;
	  align-items: center;
	  /* Updated padding for tighter edges */
	  padding: 10px 8px; 
	  font-size: 12px;
	  font-weight: 400;
	}
  
	/* Force both sides to take up equal width to perfectly center the middle nav */
	.logo, .system-time {
	  flex: 1;
	}
  
	.logo a {
	  color: #FFFFFF;
	  text-decoration: none;
	  text-transform: uppercase;
	}
  
	.nav-links {
	  display: flex;
	  justify-content: center;
	  gap: 60px;
	}
  
	.nav-links a {
	  color: #FFFFFF;
	  text-decoration: none;
	}
  
	.nav-links a:hover {
	  text-decoration: underline;
	}
  
	.system-time {
	  display: flex;
	  gap: 20px;
	  /* Push the text all the way to the right edge */
	  justify-content: flex-end; 
	}
  
	.page-content {
	  flex: 1;
	  position: relative;
	  /* Add some padding-bottom if you want to ensure long content doesn't hide behind the footer */
	  padding-bottom: 60px; 
	}
  
	/* FIXED FOOTER STYLES */
	.site-footer {
	  position: fixed; /* Glues the footer to the screen */
	  bottom: 20px;    /* Keeps it 20px away from the bottom edge */
	  left: 8px;       /* Matches the 8px left padding of your top-nav */
	  
	  display: flex;
	  flex-direction: column;
	  gap: 4px; /* Tight vertical spacing from Figma */
	  font-size: 8px; /* 8px font as specified in Figma */
	  font-weight: 400;
	  z-index: 50; /* Ensures it stays on top of any scrolling content */
	}
  
	.footer-links {
	  display: flex;
	  flex-direction: column;
	  gap: 4px;
	}
  
	.footer-links a {
	  color: #FFFFFF;
	  text-decoration: none;
	}
  
	.footer-links a:hover {
	  text-decoration: underline;
	}
  
	.copyright {
	  margin-top: 4px; /* Tiny visual break between links and copyright */
	  color: #FFFFFF;
	}
  </style>
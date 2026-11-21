import { mount } from 'svelte';
import App from './App.svelte';
import { bootstrapLink, bootstrapToken, windowBootstrapEnvironment } from './app/state/session';

const target = document.getElementById('app');
if (!target) {
	throw new Error('index.html has no #app element to mount the board into');
}

// Resolved and the URL cleared before App ever mounts: the token must never
// reach a component tree, a request, or a log by way of the address bar.
const environment = windowBootstrapEnvironment(window);
const link = bootstrapLink(environment);
const token = bootstrapToken(environment);

mount(App, { target, props: { token, link } });

// The Worker itself: everything is in share.js (a Worker's main module may only export its handlers)
import {handle} from './share.js';

export default {fetch: (req, env) => handle(req, env)};

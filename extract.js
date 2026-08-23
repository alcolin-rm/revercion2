// extract.js
const puppeteer = require('puppeteer');

const url = process.argv[2];
if (!url) {
    console.error('Usage: node extract.js <playlist_url>');
    process.exit(1);
}

(async () => {
    const browser = await puppeteer.launch({
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    const page = await browser.newPage();
    
    await page.goto(url, { waitUntil: 'networkidle2' });
    
    // Wait for vkApi to be available
    await page.waitForFunction('typeof window.vkApi !== "undefined"', { timeout: 30000 });
    
    const result = await page.evaluate(async () => {
        const url = window.location.href;
        const match = url.match(/(?:music|audio)[/_]playlist[/](\\d+_\\d+)(?:_([A-Za-z0-9]+))?/);
        if (!match) return { error: 'Could not parse playlist URL' };
        const rawId = match[1];
        const parts = rawId.split('_');
        const ownerId = parseInt(parts[0]);
        const playlistId = parseInt(parts[1]);
        const accessKey = match[2] || '';
        
        try {
            const meta = await window.vkApi.api('audio.getPlaylistById', {
                playlist_id: playlistId,
                owner_id: ownerId,
                access_key: accessKey,
                extra_fields: 'owner,duration'
            });
            if (!meta || !meta.playlist) return { error: 'Playlist not found' };
            
            const idsResp = await window.vkApi.api('audio.getAudioIdsBySource', {
                source: 'playlist',
                entity_id: `${ownerId}_${playlistId}${accessKey ? '_' + accessKey : ''}`
            });
            const audioIds = idsResp?.audios || [];
            if (!audioIds.length) return { error: 'No tracks found' };
            
            const tracks = [];
            const chunkSize = 100;
            for (let i = 0; i < audioIds.length; i += chunkSize) {
                const chunk = audioIds.slice(i, i + chunkSize);
                const ids = chunk.map(t => t.audio_id || t).join(',');
                const resp = await window.vkApi.api('audio.getById', { audios: ids });
                if (Array.isArray(resp)) {
                    resp.forEach(t => {
                        tracks.push({
                            artist: t.artist || 'Unknown',
                            title: t.title || 'Unknown',
                            duration: t.duration || 0
                        });
                    });
                }
            }
            return { tracks, total: tracks.length };
        } catch (e) {
            return { error: e.message || String(e) };
        }
    });
    
    console.log(JSON.stringify(result));
    await browser.close();
})();
/* 识别页:模型连接 / 识别参数 / 判定词表 / 测试识别 */
(function () {
  const $ = (id) => document.getElementById(id);
  window.PAGES = window.PAGES || {};

  const PRESETS = {
    deepseek: { base_url: 'https://api.deepseek.com', model: 'deepseek-v4-flash-vision-exp' },
    zhipu: { base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4v-flash' },
    dashscope: { base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-vl-plus' },
  };

  let successKeywords = [];
  let claimedKeywords = [];
  let failureKeywords = [];
  let loading = false;

  function collectVision() {
    return {
      provider: $('vProvider').value,
      base_url: $('vBaseUrl').value.trim(),
      api_key: $('vApiKey').value.trim(),
      model: $('vModel').value.trim(),
      temperature: Number($('vTemperature').value),
      detail: $('vDetail').value,
      locate_confidence_min: Number($('vMinConf').value),
      timeout_s: Number($('vTimeout').value) || 20,
      humanize_mouse: $('vHumanize').checked,
    };
  }

  async function saveVision(extra) {
    if (loading) return;
    try {
      await window.API.call('save_vision_config', Object.assign({ vision: collectVision() }, extra || {}));
    } catch (err) {
      window.APP.toast('保存失败:' + err.message, 'err');
    }
  }

  function renderChips() {
    renderChipSet('successChips', successKeywords, (list) => {
      successKeywords = list;
      saveVision({ success_keywords: list });
    });
    renderChipSet('claimedChips', claimedKeywords, (list) => {
      claimedKeywords = list;
      saveVision({ claimed_keywords: list });
    });
    renderChipSet('failureChips', failureKeywords, (list) => {
      failureKeywords = list;
      saveVision({ failure_keywords: list });
    });
  }

  function renderChipSet(containerId, list, onChange) {
    const box = $(containerId);
    box.innerHTML = '';
    list.forEach((word, index) => {
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.innerHTML = `${window.UITL.esc(word)}<button title="删除">×</button>`;
      chip.querySelector('button').addEventListener('click', () => {
        const next = list.slice();
        next.splice(index, 1);
        onChange(next);
        renderChips();
      });
      box.appendChild(chip);
    });
  }

  function bindChipInput(inputId, getList, setList, payloadKey) {
    $(inputId).addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      const value = $(inputId).value.trim();
      if (!value) return;
      const next = getList().concat([value]);
      setList(next);
      saveVision({ [payloadKey]: next });
      $(inputId).value = '';
      renderChips();
    });
  }

  window.PAGES.vision = {
    init() {
      $('vToggleKey').addEventListener('click', () => {
        const input = $('vApiKey');
        const show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        $('vToggleKey').textContent = show ? '隐藏' : '显示';
      });

      $('vTemperature').addEventListener('input', () => {
        $('vTemperatureVal').textContent = Number($('vTemperature').value).toFixed(1);
      });
      $('vTemperature').addEventListener('change', () => saveVision());
      $('vMinConf').addEventListener('input', () => {
        $('vMinConfVal').textContent = Number($('vMinConf').value).toFixed(2);
      });
      $('vMinConf').addEventListener('change', () => saveVision());

      ['vBaseUrl', 'vApiKey', 'vModel', 'vTimeout', 'vDetail', 'vHumanize'].forEach((id) => {
        $(id).addEventListener('change', () => saveVision());
      });
      $('vVerifyDelay').addEventListener('change', () =>
        saveVision({ verify_delay_s: Number($('vVerifyDelay').value) || 2.5 }));

      $('vProvider').addEventListener('change', () => {
        const preset = PRESETS[$('vProvider').value];
        if (preset) {
          $('vBaseUrl').value = preset.base_url;
          $('vModel').value = preset.model;
        }
        saveVision();
      });

      bindChipInput('successInput', () => successKeywords, (list) => { successKeywords = list; }, 'success_keywords');
      bindChipInput('claimedInput', () => claimedKeywords, (list) => { claimedKeywords = list; }, 'claimed_keywords');
      bindChipInput('failureInput', () => failureKeywords, (list) => { failureKeywords = list; }, 'failure_keywords');

      $('btnTestConn').addEventListener('click', async () => {
        const box = $('connResult');
        box.classList.remove('hidden', 'ok', 'err');
        box.textContent = '测试中…';
        try {
          const res = await window.API.call('test_vision_connection');
          box.classList.add(res && res.ok ? 'ok' : 'err');
          box.textContent = (res && res.message) || '未知结果';
        } catch (err) {
          box.classList.add('err');
          box.textContent = '测试失败:' + err.message;
        }
      });

      $('btnTestLocate').addEventListener('click', async () => {
        const box = $('locateResult');
        box.classList.remove('hidden');
        const ph = $('locatePlaceholder');
        if (ph) ph.classList.add('hidden');
        $('locateMeta').textContent = '截图中…';
        $('locateJson').textContent = '';
        $('locateImage').removeAttribute('src');
        $('locateBox').classList.add('hidden');
        try {
          const res = await window.API.call('test_locate', { source: $('locateSource').value });
          if (res.image) $('locateImage').src = res.image;
          $('locateMeta').textContent = `${res.source || ''} · ${(res.size || []).join('x')}`;
          $('locateJson').textContent = JSON.stringify(res.result, null, 2);
          if (res.box) {
            const b = res.box;
            const el = $('locateBox');
            el.style.left = (b[0] * 100) + '%';
            el.style.top = (b[1] * 100) + '%';
            el.style.width = ((b[2] - b[0]) * 100) + '%';
            el.style.height = ((b[3] - b[1]) * 100) + '%';
            el.classList.remove('hidden');
          }
          window.APP.toast(res.ok ? '测试识别完成' : ('识别失败:' + (res.error || '')),
            res.ok ? 'ok' : 'err');
        } catch (err) {
          $('locateMeta').textContent = '测试失败:' + err.message;
        }
      });
    },

    async onShow() {
      loading = true;
      try {
        const data = await window.API.call('get_vision_config');
        const v = data.vision || {};
        $('vProvider').value = v.provider || 'deepseek';
        $('vBaseUrl').value = v.base_url || '';
        $('vApiKey').value = v.api_key || '';
        $('vModel').value = v.model || '';
        $('vTemperature').value = v.temperature != null ? v.temperature : 0.2;
        $('vTemperatureVal').textContent = Number($('vTemperature').value).toFixed(1);
        $('vDetail').value = v.detail || 'auto';
        $('vMinConf').value = v.locate_confidence_min != null ? v.locate_confidence_min : 0.7;
        $('vMinConfVal').textContent = Number($('vMinConf').value).toFixed(2);
        $('vTimeout').value = v.timeout_s || 20;
        $('vVerifyDelay').value = data.verify_delay_s != null ? data.verify_delay_s : 2.5;
        $('vHumanize').checked = !!v.humanize_mouse;
        successKeywords = data.success_keywords || [];
        claimedKeywords = data.claimed_keywords || [];
        failureKeywords = data.failure_keywords || [];
        const prompts = await window.API.call('get_prompts');
        $('locatePromptText').textContent = prompts.locate || '';
        $('verifyPromptText').textContent = prompts.verify || '';
      } catch (err) {
        window.APP.toast('读取识别配置失败:' + err.message, 'err');
      } finally {
        loading = false;
      }
      renderChips();
    },
  };
})();
